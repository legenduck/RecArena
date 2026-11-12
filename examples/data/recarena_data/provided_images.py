"""Optionally download images, or register an existing collection for self hosting."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import time

import duckdb
from PIL import Image

from recarena_contracts.artifacts import digest, make_manifest, write_json
from recarena_contracts.assets import LocalImageReference

MEDIA_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}


def validate_image(row, root, source_key, *, validation='full'):
    parent, index, relative, ok, expected_bytes, url, expected_url = row
    if not ok:
        return None, 'source_download_failed'
    if not url or url != expected_url:
        return None, 'metadata_url_mismatch'
    if not isinstance(index, int) or index < 0 or not isinstance(parent, str):
        return None, 'invalid_source_identifier'
    expected_path = f'large/{parent[-2:]}/{parent}_{index:02d}.jpg'
    if relative != expected_path:
        return None, 'source_path_mismatch'
    if validation == 'manifest':
        if not isinstance(expected_bytes, int) or not 0 < expected_bytes <= 32 * 1024 * 1024:
            return None, 'invalid_manifest_size'
        # Record the researcher's declared download path and size. Content hash
        # and dimensions are unknown in this mode, not fabricated or verified.
        return LocalImageReference(asset_id=f'{parent}_{index:02d}', source_key=source_key,
            source_parent_asin=parent, source_index=index, path=relative,
            size_bytes=expected_bytes, media_type='image/jpeg'), None
    try:
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            return None, 'path_outside_collection'
        with path.open('rb') as stream:
            content = stream.read(32 * 1024 * 1024 + 1)
        if not content or len(content) > 32 * 1024 * 1024 or len(content) != expected_bytes:
            return None, 'size_mismatch'
        with Image.open(io.BytesIO(content), formats=list(MEDIA_TYPES)) as image:
            width, height = image.size
            media_type = MEDIA_TYPES[image.format]
            if width < 1 or height < 1 or width * height > 40_000_000:
                return None, 'invalid_dimensions'
            image.load()  # actually decode; file suffix/status alone does not prove a valid image
        reference = LocalImageReference(asset_id=f'{parent}_{index:02d}', source_key=source_key,
            source_parent_asin=parent, source_index=index, path=relative,
            sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
            media_type=media_type, width=width, height=height)
        return reference, None
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, 'missing_or_invalid_image'


def publish_images(*, source_manifest, metadata, root, source_key, catalog_id, output, workers=8, validation='full',
                   download_performed=False):
    if validation not in {'full', 'manifest'}:
        raise ValueError('Unknown image validation mode')
    source_manifest, metadata, root = (Path(p).resolve(strict=True) for p in (source_manifest, metadata, root))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    initial = {str(p): digest(p) for p in (source_manifest, metadata)}
    con = duckdb.connect(config={'threads': 2,
        'memory_limit': os.environ.get('RECARENA_DATA_MEMORY_LIMIT', '2GB')})
    counts = Counter(source_images=0, referenced_images=0, validated_bytes=0)
    products = set()
    valid_products = set()
    identifiers = set()
    started = time.monotonic()
    try:
        # Match each downloaded image to the same metadata parent and image position.
        result = con.execute("""
            SELECT i.parent_asin,i.idx,i.path,i.ok,i.bytes,i.url,
                   coalesce(nullif(json_extract_string(m.json,'$.images[' || CAST(i.idx AS VARCHAR) || '].large'),''),
                            nullif(json_extract_string(m.json,'$.images[' || CAST(i.idx AS VARCHAR) || '].hi_res'),''),
                            nullif(json_extract_string(m.json,'$.images[' || CAST(i.idx AS VARCHAR) || '].thumb'),''))
            FROM read_parquet(?) i LEFT JOIN read_parquet(?) m USING(parent_asin)
            ORDER BY i.parent_asin,i.idx
        """, [str(source_manifest), str(metadata)])
        with (output / 'asset_index.jsonl').open('x') as stream, \
                (output / 'excluded_images.jsonl').open('x') as excluded, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            while batch := result.fetchmany(2048):
                validate = lambda item: validate_image(item, root, source_key, validation=validation)
                mapped = map(validate, batch) if validation == 'manifest' else pool.map(validate, batch)
                for row, (reference, reason) in zip(batch, mapped):
                    counts['source_images'] += 1
                    products.add(row[0])
                    if reference is None:
                        counts[reason] += 1
                        excluded.write(json.dumps({'parent_asin': row[0], 'index': row[1], 'reason': reason}) + '\n')
                    else:
                        if reference.asset_id in identifiers:
                            raise ValueError('Duplicate parent/image-position identity in supplied manifest')
                        identifiers.add(reference.asset_id)
                        valid_products.add(reference.source_parent_asin)
                        counts['referenced_images'] += 1
                        counts['referenced_bytes'] += reference.size_bytes
                        if validation == 'full':
                            counts['validated_bytes'] += reference.size_bytes
                        stream.write(reference.model_dump_json() + '\n')
                if counts['source_images'] % 32768 == 0:
                    print(json.dumps({'processed': counts['source_images'], 'referenced': counts['referenced_images'],
                        'validation_mode': validation,
                        'elapsed_seconds': round(time.monotonic() - started, 2)}), flush=True)
        counts['source_products'] = len(products)
        counts['products_with_reference'] = len(valid_products)
        counts['products_without_reference'] = len(products - valid_products)
        if validation == 'full':
            counts['products_with_valid_image'] = len(valid_products)
            counts['products_without_valid_image'] = len(products - valid_products)
        for path in (source_manifest, metadata):
            if digest(path) != initial[str(path)]:
                raise ValueError('Prepared metadata/manifest changed during image validation')
        # A common, explicitly labelled missing-image graphic; never a generated product image.
        (output / 'placeholder.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
            '<rect width="400" height="300" fill="#f1f3f5"/>'
            '<text x="200" y="155" text-anchor="middle" font-family="sans-serif" fill="#59636e">Image unavailable</text></svg>\n')
        report = {'source_manifest_sha256': initial[str(source_manifest)], 'metadata_sha256': initial[str(metadata)],
            'source_key': source_key, 'source_root': str(root), 'counts': dict(counts),
            'elapsed_seconds': time.monotonic() - started, 'download_performed': download_performed,
            'image_copies_created': 0, 'validation_mode': validation,
            'validation': 'metadata URL + relative path + size + decode + SHA256' if validation == 'full'
                else 'download manifest status/size + metadata URL + relative path; image bytes not read',
            'media_type_source': 'decoded image format' if validation == 'full' else 'declared .jpg download path',
            'runtime_integrity': 'request-time path, regular-file and size checks; stat-based HTTP caching'}
        write_json(output / 'validation_report.json', report)
        manifest = make_manifest(output, 'assets', {'storage': 'referenced_local_collection', 'source_key': source_key,
            'validation_mode': validation,
            'max_bytes': 32 * 1024 * 1024,
            **({'max_pixels': 40_000_000} if validation == 'full' else {})}, sources=[source_manifest, metadata],
            parents=[catalog_id], counts=dict(counts),
            warnings=['External image collection must remain available read-only; no runtime downloads.'], source_scope="examples/data")
        return {'manifest_path': str(output / 'manifest.json'), 'artifact_id': manifest['artifact_id'], **report}
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-manifest', type=Path, help='Register an existing downloaded collection')
    source.add_argument('--download', action='store_true', help='Download metadata image URLs into a new --root directory')
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source-key', required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--validation', choices=('full', 'manifest'), default='full',
        help='full decodes/hashes files; manifest registers prepared download references with unknown hashes/dimensions')
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    if args.download and args.validation != 'full':
        parser.error('New downloads require full validation to determine the actual image format')
    if args.output.exists():
        parser.error('--output must be a new directory')
    if args.download:
        from recarena_data.download_images import download_images
        args.source_manifest = download_images(metadata=args.metadata, root=args.root, workers=args.workers)
    print(json.dumps(publish_images(source_manifest=args.source_manifest, metadata=args.metadata,
        root=args.root, source_key=args.source_key, catalog_id=args.catalog, output=args.output,
        workers=args.workers, validation=args.validation, download_performed=args.download), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
