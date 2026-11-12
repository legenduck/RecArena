"""Bounded-memory import of sealed JSONL catalogs using the existing entity contracts."""
from collections import Counter, defaultdict
import json
import logging
from pathlib import Path

from psycopg.types.json import Jsonb

from recarena_contracts.artifacts import digest, verify_manifest
from recarena_contracts.catalog import CatalogPackage
from recarena_contracts.manifest import ArtifactManifest
from recarena_contracts.models import Product, Variant, Review, Interaction, TaskVersion
from recarena_platform.db import catalog as db
from recarena_platform.catalog.history import fixed_history_fingerprint
from recarena_platform.task_validation import validate_task_utility
from recarena_platform.catalog.reviews import review_document
from recarena_platform.catalog.review_statistics import store_review_statistics

logger = logging.getLogger(__name__)


def records(path, schema):
    with path.open() as stream:
        for line in stream:
            yield schema.model_validate_json(line)


def import_package(session, manifest_path):
    """Caller owns one transaction; all validation failures roll back the complete import."""
    path = Path(manifest_path).resolve()
    manifest = verify_manifest(path)
    root = path.parent
    package = CatalogPackage.model_validate_json((root / 'package.json').read_text())
    if manifest['artifact_type'] != 'catalog_snapshot' or manifest['artifact_id'] != package.dataset_snapshot_id:
        raise ValueError('Package catalog manifest mismatch')
    for cls, identifier in ((db.DatasetSnapshot, package.dataset_snapshot_id),
                            (db.ReviewSnapshot, package.review_snapshot_id),
                            (db.HistorySnapshot, package.history_snapshot_id)):
        if session.get(cls, identifier) is not None:
            raise ValueError('Immutable snapshot ID already registered')
    session.add(db.DatasetSnapshot(id=package.dataset_snapshot_id, manifest=manifest))
    session.flush()
    common = {**manifest, 'files': [], 'parent_artifact_ids': [package.dataset_snapshot_id],
              'source_files': [*manifest['source_files'], {'name': path.name, 'sha256': digest(path)}]}
    review_manifest = {**common, 'artifact_id': package.review_snapshot_id,
        'artifact_type': 'review_snapshot', 'counts': {'reviews': manifest['counts']['reviews']}}
    history_manifest = {**common, 'artifact_id': package.history_snapshot_id,
        'artifact_type': 'history_snapshot', 'counts': {'interactions': manifest['counts']['interactions']}}
    ArtifactManifest.model_validate(review_manifest)
    ArtifactManifest.model_validate(history_manifest)
    session.add(db.ReviewSnapshot(id=package.review_snapshot_id, dataset_snapshot_id=package.dataset_snapshot_id,
        cutoff=package.review_cutoff, manifest=review_manifest))
    session.add(db.HistorySnapshot(id=package.history_snapshot_id, dataset_snapshot_id=package.dataset_snapshot_id,
        manifest=history_manifest))
    session.flush()
    connection = session.connection().connection.driver_connection
    counts = Counter(products=0, variants=0, reviews=0, interactions=0, tasks=0)
    products = {}
    with connection.cursor() as cursor:
        with cursor.copy('COPY products (dataset_snapshot_id, product_id, document) FROM STDIN') as copy:
            for product in records(root / package.products_file, Product):
                if product.dataset_snapshot_id != package.dataset_snapshot_id or product.product_id in products:
                    raise ValueError('Duplicate product or mismatched catalog')
                products[product.product_id] = (product.currency, product.display_review_count, product.display_rating)
                copy.write_row((package.dataset_snapshot_id, product.product_id, Jsonb(product.model_dump(mode='json'))))
                counts['products'] += 1
        option_keys = set()
        with cursor.copy('COPY variants (dataset_snapshot_id, variant_id, product_id, unit_price_minor, currency, '
                         'is_available, is_purchasable, document) FROM STDIN') as copy:
            for variant in records(root / package.variants_file, Variant):
                if (variant.dataset_snapshot_id != package.dataset_snapshot_id or variant.product_id not in products
                        or variant.currency != products[variant.product_id][0]):
                    raise ValueError('Variant catalog/product/currency mismatch')
                key = (variant.product_id, tuple(sorted(variant.option_values.items())))
                if key in option_keys:
                    raise ValueError('Ambiguous duplicate option combination')
                option_keys.add(key)
                copy.write_row((package.dataset_snapshot_id, variant.variant_id, variant.product_id,
                    variant.unit_price_minor, variant.currency, variant.is_available, variant.is_purchasable,
                    Jsonb(variant.model_dump(mode='json'))))
                counts['variants'] += 1
        del option_keys
        review_counts, rating_sums = Counter(), Counter()
        rating_counts = defaultdict(Counter)
        with cursor.copy('COPY reviews (review_snapshot_id, review_id, dataset_snapshot_id, product_id, timestamp_utc, document) FROM STDIN') as copy:
            for review in records(root / package.reviews_file, Review):
                if (review.review_snapshot_id != package.review_snapshot_id or review.product_id not in products
                        or (package.review_cutoff is not None and review.timestamp_utc > package.review_cutoff)):
                    raise ValueError('Review snapshot/product/cutoff mismatch')
                copy.write_row((package.review_snapshot_id, review.review_id, package.dataset_snapshot_id,
                    review.product_id, review.timestamp_utc, Jsonb(review_document(review))))
                counts['reviews'] += 1
                review_counts[review.product_id] += 1
                rating_sums[review.product_id] += review.rating
                rating_counts[review.product_id][review.rating] += 1
                if counts['reviews'] % 262144 == 0:
                    logger.info('Imported %d public reviews (transaction not committed yet)', counts['reviews'])
        for product_id, (_, count, rating) in products.items():
            expected_count = review_counts[product_id]
            expected_rating = rating_sums[product_id] / expected_count if expected_count else None
            if count != expected_count or rating != expected_rating:
                raise ValueError('Displayed ratings/counts must use the public review snapshot')
        store_review_statistics(session, package.dataset_snapshot_id, package.review_snapshot_id,
            products, rating_counts)
        del rating_counts
        with (root / package.history_file).open() as stream:
            users = {json.loads(line)['user_id'] for line in stream}
        with cursor.copy('COPY historical_users (history_snapshot_id, user_id) FROM STDIN') as copy:
            for user in sorted(users):
                copy.write_row((package.history_snapshot_id, user))
        counts['users'] = len(users)
        del users
        with cursor.copy('COPY historical_interactions (history_snapshot_id, user_id, product_id, dataset_snapshot_id, timestamp_utc, document) FROM STDIN') as copy:
            for interaction in records(root / package.history_file, Interaction):
                if interaction.history_snapshot_id != package.history_snapshot_id or interaction.product_id not in products:
                    raise ValueError('History snapshot/product mismatch')
                # The existing primary key rejects repeated user-parent pairs, even across batches.
                copy.write_row((package.history_snapshot_id, interaction.user_id, interaction.product_id,
                    package.dataset_snapshot_id, interaction.timestamp_utc, Jsonb(interaction.model_dump(mode='json'))))
                counts['interactions'] += 1
                if counts['interactions'] % 262144 == 0:
                    logger.info('Imported %d historical interactions (transaction not committed yet)', counts['interactions'])
    for task in records(root / package.tasks_file, TaskVersion):
        if task.catalog_snapshot_id != package.dataset_snapshot_id:
            raise ValueError('Task catalog mismatch')
        validate_task_utility(session, task)
        session.add(db.TaskVersion(id=f'{task.task_id}:v{task.version}', task_id=task.task_id, version=task.version,
            dataset_snapshot_id=task.catalog_snapshot_id, document=task.model_dump(mode='json')))
        counts['tasks'] += 1
    session.flush()
    if any(manifest['counts'].get(key) != count for key, count in counts.items()):
        raise ValueError('Catalog package count mismatch')
    if fixed_history_fingerprint(session, package.history_snapshot_id) != package.history_fingerprint:
        raise ValueError('Catalog package training-history fingerprint mismatch')
    if verify_manifest(path) != manifest:
        raise ValueError('Catalog package changed during import')
    return package
