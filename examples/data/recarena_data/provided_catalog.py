"""Bridge explicitly supplied Amazon prepared files to immutable sandbox entities.

No filtering/preprocessing/training pipeline is rerun. History is supplied as
prepared Parquet files; public reviews stay separate. No model artifacts are read.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time

import duckdb

from recarena_contracts.artifacts import digest, make_manifest, verify_manifest, write_json
from recarena_contracts.assets import LocalImageReference
from recarena_contracts.catalog import CatalogPackage
from recarena_contracts.history import history_fingerprint_sorted
from recarena_contracts.models import Interaction, Product, Review, Variant
from recarena_data.image_sources import image_entries

OPTION_FIELDS = {'Color': 'color', 'Size': 'size', 'Capacity': 'capacity', 'Style': 'style', 'Pattern': 'pattern'}
NON_SEARCH_DETAILS = {'brand', 'best sellers rank', 'customer reviews', 'asin', 'parent asin',
                      'average rating', 'rating number', 'ratings', 'review count'}


def price_minor(value):
    if value is None:
        return None, 'missing_price'
    if isinstance(value, bool):
        return None, 'invalid_price'
    try:
        number = Decimal(str(value))
        scaled = number * 100
        if not number.is_finite() or scaled < 0 or scaled != scaled.to_integral_value() or scaled > 2**31 - 1:
            return None, 'invalid_price'
        return int(scaled), None
    except (InvalidOperation, ValueError):
        return None, 'invalid_price'


def strings(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item.strip()]
    raise ValueError('Unexpected prepared metadata text shape')


def helpful_votes(value):
    """Keep invalid source counters as provenance, never fabricate a valid count."""
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        return None, {'invalid_source_helpful_vote': value, 'helpful_votes_status': 'invalid_source_value'}
    return value, {}


def map_product(parent, metadata, *, catalog_id, images, review_count, rating):
    if metadata.get('parent_asin') != parent:
        raise ValueError('Metadata parent identifier mismatch')
    details = metadata.get('details') or {}
    if not isinstance(details, dict):
        raise ValueError('Unexpected prepared details shape')
    attributes = {}
    for key, value in details.items():
        if key.strip().casefold() not in NON_SEARCH_DETAILS:
            attributes[OPTION_FIELDS.get(key, key)] = value
    options = {target: details[source].strip() for source, target in OPTION_FIELDS.items()
               if isinstance(details.get(source), str) and details[source].strip()}
    brand = details.get('Brand')
    brand = brand.strip() if isinstance(brand, str) and brand.strip() else None
    title = metadata.get('title')
    has_title = isinstance(title, str) and bool(title.strip())
    price, price_reason = price_minor(metadata.get('price'))
    reasons = ([price_reason] if price_reason else []) + ([] if has_title else ['missing_title'])
    unavailable_reasons = [reason for reason in reasons if reason != 'missing_price']
    urls = [url for _, url in image_entries(metadata)]
    product = Product(dataset_snapshot_id=catalog_id, product_id=parent, source_parent_asin=parent,
        title=title if has_title else '[Title unavailable]', brand=brand,
        description='\n'.join(strings(metadata.get('description'))), features=strings(metadata.get('features')),
        categories=strings(metadata.get('categories')), attributes=attributes, image_asset_ids=images, image_urls=urls,
        currency='USD', display_review_count=review_count, display_rating=rating,
        product_status='active' if has_title else 'excluded', source_provenance={
            'origin': 'researcher_prepared_amazon_reviews_2023', 'source_parent_asin': parent,
            'brand_field': 'details.Brand', 'title_missing': not has_title,
            'excluded_from_purchase_reasons': unavailable_reasons,
            'price_status': price_reason or 'provided',
            'rating_source': 'declared_public_review_snapshot',
            'metadata_is_historical_page_reconstruction': False})
    variant = Variant(dataset_snapshot_id=catalog_id, variant_id=parent + '-listed', product_id=parent,
        source_asin=None, option_values=options, attributes_override={}, unit_price_minor=price,
        currency='USD', image_asset_ids=images, image_urls=urls,
        is_available=not unavailable_reasons, is_purchasable=not unavailable_reasons,
        provenance={'representation': 'single_fixed_metadata_offer', 'price_field': 'price',
            'option_fields': {key: f'details.{source}' for source, key in OPTION_FIELDS.items() if key in options},
            'source_child_asin_verified': False, 'cartesian_variants_created': False,
            'availability_scope': 'static listed offer for simulation; not live stock',
            'price_status': price_reason or 'provided',
            'excluded_from_purchase_reasons': unavailable_reasons})
    return product, variant, reasons


def prepare_public_reviews(*, metadata, reviews, output, catalog_id, review_id, cutoff=None):
    """Seal the supplied public reviews independently of models and image preparation."""
    metadata, reviews = (Path(p).resolve(strict=True) for p in (metadata, reviews))
    initial = {str(p): digest(p) for p in (metadata, reviews)}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(config={'threads': 2,
        'memory_limit': os.environ.get('RECARENA_DATA_MEMORY_LIMIT', '2GB')})
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    count = 0
    invalid_helpful = 0
    stats = defaultdict(lambda: [0, 0.0])
    started = time.monotonic()
    try:
        products = {row[0] for row in con.execute('SELECT parent_asin FROM read_parquet(?)', [str(metadata)]).fetchall()}
        result = con.execute('SELECT file_row_number,parent_asin,asin,user_id,rating,title,text,timestamp,'
            'verified_purchase,helpful_vote FROM read_parquet(?,file_row_number=true) ORDER BY file_row_number', [str(reviews)])
        with (output / 'reviews.jsonl').open('x') as stream:
            while batch := result.fetchmany(4096):
                for ordinal, parent, asin, user, rating, title, body, timestamp, verified, helpful in batch:
                    if parent not in products or not isinstance(timestamp, int):
                        raise ValueError('Invalid prepared review product/timestamp')
                    occurred = epoch + timedelta(milliseconds=timestamp)
                    if cutoff is not None and occurred >= cutoff:
                        raise ValueError('Public review is not before the declared exclusive cutoff')
                    helpful, helpful_provenance = helpful_votes(helpful)
                    invalid_helpful += bool(helpful_provenance)
                    review = Review(review_snapshot_id=review_id, review_id=f'provided-{ordinal:012d}',
                        product_id=parent, source_asin=asin, source_user_id=user,
                        display_author_alias='Reviewer-' + hashlib.sha256(str(user).encode()).hexdigest()[:12],
                        rating=rating, title=title or '', body=body or '', timestamp_utc=occurred,
                        verified_purchase=verified, helpful_votes=helpful,
                        source_provenance={'source_row': ordinal, 'source_sha256': initial[str(reviews)],
                                           'timestamp_unit': 'milliseconds', **helpful_provenance})
                    stream.write(review.model_dump_json() + '\n')
                    stats[parent][0] += 1
                    stats[parent][1] += rating
                    count += 1
                if count % 262144 == 0:
                    print(json.dumps({'stage': 'public_reviews', 'rows': count,
                        'elapsed_seconds': round(time.monotonic() - started, 2)}), flush=True)
        write_json(output / 'review_stats.json', {p: [n, total / n] for p, (n, total) in stats.items()})
        if any(digest(p) != initial[str(p)] for p in (metadata, reviews)):
            raise ValueError('Public review input changed during preparation')
        write_json(output / 'inputs.json', {'metadata_sha256': initial[str(metadata)],
            'reviews_sha256': initial[str(reviews)], 'exclusive_cutoff': cutoff.isoformat() if cutoff else None})
        write_json(output / 'data_quality.json', {'invalid_helpful_vote_rows': invalid_helpful,
            'handling': 'helpful_votes=null; original value retained in source_provenance; review retained'})
        make_manifest(output, 'review_snapshot', {'exclusive_cutoff': cutoff.isoformat() if cutoff else None},
            sources=[metadata, reviews], parents=[catalog_id], counts={'reviews': count}, artifact_id=review_id, source_scope="examples/data")
        return output / 'manifest.json'
    finally:
        con.close()


def publish_catalog(*, metadata, reviews, image_manifest=None, output, catalog_id, review_id, history_id,
                    history_parquets=(), review_cutoff=None, public_review_manifest=None,
                    threads=2, memory_limit=None):
    if not history_parquets:
        raise ValueError('Supply explicit prepared history Parquet files')
    if threads < 1:
        raise ValueError('threads must be positive')
    paths = {name: Path(value).resolve(strict=True) for name, value in {
        'metadata': metadata, 'reviews': reviews}.items()}
    paths.update({f'history_{i}': Path(p).resolve(strict=True) for i, p in enumerate(history_parquets)})
    if image_manifest:
        paths['image_manifest'] = Path(image_manifest).resolve(strict=True)
        assets = verify_manifest(paths['image_manifest'])
        if assets['artifact_type'] != 'assets' or assets['parent_artifact_ids'] != [catalog_id]:
            raise ValueError('Supplied catalog/history/image ancestry mismatch')
    public = None
    if public_review_manifest:
        paths['public_review_manifest'] = Path(public_review_manifest).resolve(strict=True)
        public = verify_manifest(paths['public_review_manifest'])
        if (public['artifact_type'] != 'review_snapshot' or public['artifact_id'] != review_id
                or public['parent_artifact_ids'] != [catalog_id]):
            raise ValueError('Prepared public review ancestry mismatch')
    initial = {name: digest(path) for name, path in paths.items()}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    counts = Counter(products=0, variants=0, reviews=0, interactions=0, users=0, tasks=0,
        purchasable_products=0, excluded_products=0, missing_price=0, invalid_price=0,
        missing_title=0, missing_image=0)
    images = defaultdict(list)
    if image_manifest:
        with (paths['image_manifest'].parent / 'asset_index.jsonl').open() as stream:
            for line in stream:
                reference = LocalImageReference.model_validate_json(line)
                images[reference.source_parent_asin].append((reference.source_index, reference.asset_id))
    con = duckdb.connect(config={'threads': threads,
        'memory_limit': memory_limit or os.environ.get('RECARENA_DATA_MEMORY_LIMIT', '2GB')})
    started = time.monotonic()
    try:
        if public:
            public_root = paths['public_review_manifest'].parent
            inputs = json.loads((public_root / 'inputs.json').read_text())
            if inputs != {'metadata_sha256': initial['metadata'], 'reviews_sha256': initial['reviews'],
                          'exclusive_cutoff': review_cutoff.isoformat() if review_cutoff else None}:
                raise ValueError('Prepared public review input/cutoff mismatch')
            review_stats = json.loads((public_root / 'review_stats.json').read_text())
        else:
            review_stats = {parent: (count, rating) for parent, count, rating in con.execute(
                'SELECT parent_asin, count(*), avg(rating) FROM read_parquet(?) GROUP BY parent_asin',
                [str(paths['reviews'])]).fetchall()}
        product_ids = set()
        result = con.execute('SELECT parent_asin,json FROM read_parquet(?) ORDER BY parent_asin', [str(paths['metadata'])])
        with (output / 'products.jsonl').open('x') as products, (output / 'variants.jsonl').open('x') as variants:
            while batch := result.fetchmany(2048):
                for parent, raw in batch:
                    if parent in product_ids:
                        raise ValueError('Duplicate prepared parent product')
                    product_ids.add(parent)
                    image_ids = [identifier for _, identifier in sorted(images.get(parent, []))]
                    count, rating = review_stats.get(parent, (0, None))
                    product, variant, reasons = map_product(parent, json.loads(raw), catalog_id=catalog_id,
                        images=image_ids, review_count=count, rating=rating)
                    products.write(product.model_dump_json() + '\n')
                    variants.write(variant.model_dump_json() + '\n')
                    counts['products'] += 1
                    counts['variants'] += 1
                    counts['purchasable_products' if variant.is_purchasable else 'excluded_products'] += 1
                    counts['missing_image'] += int(not image_ids and not product.image_urls)
                    counts.update(reasons)
        if set(review_stats) - product_ids or set(images) - product_ids:
            raise ValueError('Prepared reviews/images reference unknown parent products')
        print(json.dumps({'stage': 'catalog', 'counts': dict(counts)}), flush=True)
        del images, review_stats
        result = None if public else con.execute('SELECT file_row_number,parent_asin,asin,user_id,rating,title,text,timestamp,'
            'verified_purchase,helpful_vote FROM read_parquet(?,file_row_number=true) ORDER BY file_row_number',
            [str(paths['reviews'])])
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        if public:
            os.link(public_root / 'reviews.jsonl', output / 'reviews.jsonl')
            counts['reviews'] = public['counts']['reviews']
        with (output / 'reviews.jsonl').open('a' if public else 'x') as stream:
            while not public and (batch := result.fetchmany(4096)):
                for ordinal, parent, asin, user, rating, title, body, timestamp, verified, helpful in batch:
                    if parent not in product_ids or not isinstance(timestamp, int):
                        raise ValueError('Invalid prepared review product/timestamp')
                    helpful, helpful_provenance = helpful_votes(helpful)
                    review = Review(review_snapshot_id=review_id, review_id=f'provided-{ordinal:012d}',
                        product_id=parent, source_asin=asin, source_user_id=user,
                        display_author_alias='Reviewer-' + hashlib.sha256(str(user).encode()).hexdigest()[:12],
                        rating=rating, title=title or '', body=body or '',
                        timestamp_utc=epoch + timedelta(milliseconds=timestamp), verified_purchase=verified,
                        helpful_votes=helpful, source_provenance={'source_row': ordinal,
                            'source_sha256': initial['reviews'], 'timestamp_unit': 'milliseconds', **helpful_provenance})
                    if review_cutoff is not None and review.timestamp_utc >= review_cutoff:
                        raise ValueError('Public review is not before the declared exclusive cutoff')
                    stream.write(review.model_dump_json() + '\n')
                    counts['reviews'] += 1
                if counts['reviews'] % 262144 == 0:
                    print(json.dumps({'stage': 'reviews', 'rows': counts['reviews'],
                        'elapsed_seconds': round(time.monotonic() - started, 2)}), flush=True)
        users = set()
        def history_records():
            rows = con.execute('SELECT user_id,parent_asin,timestamp,rating,asin FROM read_parquet(?) '
                'ORDER BY user_id,parent_asin,timestamp',
                [[str(paths[f'history_{i}']) for i in range(len(history_parquets))]])
            previous = None
            while batch := rows.fetchmany(4096):
                for user, product, timestamp, rating, asin in batch:
                    key = (user, product)
                    if key == previous:
                        raise ValueError('Prepared history contains duplicate user-product pairs; no implicit deduplication')
                    previous = key
                    if not isinstance(timestamp, int):
                        raise ValueError('Prepared history timestamp must be integer milliseconds')
                    occurred = epoch + timedelta(milliseconds=timestamp)
                    if review_cutoff is not None and occurred >= review_cutoff:
                        raise ValueError('Prepared history reaches the held-out test period')
                    yield user, product, occurred, rating, asin
        def write_history(stream):
            for user, product, occurred, rating, asin in history_records():
                if product not in product_ids:
                    raise ValueError('Prepared history references an unknown product')
                interaction = Interaction(history_snapshot_id=history_id, user_id=user,
                    product_id=product, timestamp_utc=occurred, rating=rating, source_asin=asin)
                stream.write(interaction.model_dump_json() + '\n')
                users.add(interaction.user_id)
                counts['interactions'] += 1
                yield interaction.user_id, interaction.product_id, interaction.timestamp_utc.timestamp()
        with (output / 'history.jsonl').open('x') as stream:
            fingerprint = history_fingerprint_sorted(write_history(stream))
        counts['users'] = len(users)
        (output / 'tasks.jsonl').write_text('')
        package = CatalogPackage(dataset_snapshot_id=catalog_id, review_snapshot_id=review_id,
            history_snapshot_id=history_id, review_cutoff=review_cutoff, history_fingerprint=fingerprint)
        write_json(output / 'package.json', package.model_dump(mode='json'))
        for name, path in paths.items():
            if digest(path) != initial[name]:
                raise ValueError('A supplied input changed during packaging')
        if public and verify_manifest(paths['public_review_manifest']) != public:
            raise ValueError('Prepared public reviews changed during packaging')
        report = {'counts': dict(counts), 'mapping': 'product_id = source_parent_asin',
            'inputs': {name: {'path': str(path), 'sha256': initial[name]} for name, path in paths.items()},
            'history_fingerprint': fingerprint, 'preprocessing_rerun': False,
            'public_reviews': 'all rows of explicitly supplied prepared review snapshot',
            'exclusive_review_cutoff': review_cutoff.isoformat() if review_cutoff else None,
            'history': 'all rows of explicitly supplied history parquet files',
            'image_delivery': 'local_assets_with_url_fallback' if image_manifest else 'external_urls',
            'elapsed_seconds': time.monotonic() - started,
            'limitations': ['Prepared public reviews are supplied research data, not the full Amazon review population.',
                'One fixed listed offer per parent; no verified child-ASIN inventory or fabricated combinations.',
                'Missing titles have an explicit unavailable label and are excluded from search/purchase.',
                'Metadata and availability do not reconstruct a historical or live Amazon page.']}
        write_json(output / 'validation_report.json', report)
        manifest = make_manifest(output, 'catalog_snapshot', {'adapter': 'provided-amazon-parquet-v1',
            'package': package.model_dump(mode='json'), 'inputs': report['inputs']}, sources=list(paths.values()),
            counts=dict(counts), artifact_id=catalog_id, warnings=report['limitations'], source_scope="examples/data")
        return {'manifest_path': str(output / 'manifest.json'), 'manifest': manifest, 'report': report}
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('metadata', 'reviews', 'output'):
        parser.add_argument('--' + argument, type=Path, required=True)
    parser.add_argument('--image-manifest', type=Path,
        help='Optional downloaded image references; omitted means browser-direct metadata URLs')
    parser.add_argument('--history-parquet', type=Path, action='append', required=True)
    parser.add_argument('--review-cutoff', type=lambda value: datetime.fromisoformat(value))
    parser.add_argument('--public-review-manifest', type=Path)
    for argument in ('catalog', 'review', 'history'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args()
    result = publish_catalog(metadata=args.metadata, reviews=args.reviews,
        image_manifest=args.image_manifest, output=args.output, catalog_id=args.catalog,
        review_id=args.review, history_id=args.history, history_parquets=args.history_parquet or (),
        review_cutoff=args.review_cutoff, public_review_manifest=args.public_review_manifest)
    print(json.dumps({'manifest_path': result['manifest_path'], 'report': result['report']}, allow_nan=False))


if __name__ == '__main__':
    main()
