"""Prepare one Amazon category through the common time split, without downstream jobs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import duckdb

from .core import filter_core
from .metadata import filter_metadata, select_catalog
from .reviews import deduplicate_reviews, filter_reviews, sort_reviews
from .split import normalize_ratios, split_by_time


def prepare(*, category, metadata, reviews, output, threads=None, memory_limit='8GB', ratios=(.8, .1, .1)):
    metadata, reviews = (Path(path).resolve(strict=True) for path in (metadata, reviews))
    output = Path(output).resolve()
    threads = threads if threads is not None else (os.cpu_count() or 1)
    if threads < 1 or not category.strip():
        raise ValueError('A category name and positive thread count are required')
    ratios = normalize_ratios(ratios)
    files = {'metadata_filtered': 'meta_filtered.parquet', 'reviews_filtered': 'review_filtered.parquet',
             'reviews_sorted': 'review_sorted.parquet', 'reviews_deduplicated': 'review_deduped.parquet',
             'reviews_core': 'review_5core.parquet', 'metadata': 'meta_final.parquet',
             **{name: f'splits/review_{name}.parquet' for name in ('train', 'valid', 'test')}}
    paths = {key: output / path for key, path in files.items()}
    output.mkdir(parents=True, exist_ok=False)
    report = {'format': 'recarena-amazon-prepared-v1', 'category': category,
              'created_at': datetime.now(timezone.utc).isoformat(),
              'sources': {'metadata': str(metadata), 'reviews': str(reviews)}, 'files': files,
              'settings': {'threads': threads, 'memory_limit': memory_limit, 'user_core': 5, 'item_core': 5},
              'stages': {}}
    current = None

    def stage(name, function, *args, **kwargs):
        nonlocal current
        current = name
        started = time.monotonic()
        value = function(*args, **kwargs)
        report['stages'][name] = {**value, 'elapsed_seconds': time.monotonic() - started}
        print(json.dumps({'stage': name, **report['stages'][name]}), flush=True)
        return value

    try:
        with duckdb.connect(config={'threads': threads, 'memory_limit': memory_limit,
                                    'temp_directory': str(output / '.spill'),
                                    'preserve_insertion_order': False}) as connection:
            stage('metadata_filter', filter_metadata, connection, metadata, paths['metadata_filtered'])
            stage('review_filter', filter_reviews, connection, reviews, paths['metadata_filtered'], paths['reviews_filtered'])
            stage('review_sort', sort_reviews, connection, paths['reviews_filtered'], paths['reviews_sorted'])
            stage('review_deduplicate', deduplicate_reviews, connection, paths['reviews_sorted'], paths['reviews_deduplicated'])
            stage('review_core', filter_core, connection, paths['reviews_deduplicated'], paths['reviews_core'])
            stage('catalog', select_catalog, connection, paths['metadata_filtered'], paths['reviews_core'], paths['metadata'])
            report['time_split'] = stage('time_split', split_by_time, connection,
                paths['reviews_core'], output / 'splits', ratios=ratios)
        report['status'] = 'complete'
        (output / 'prepared.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return report
    except Exception as error:
        report.update(status='failed', failed_stage=current, error=str(error))
        (output / 'failed.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--category', required=True)
    parser.add_argument('--metadata', type=Path, required=True, help='Original meta_<category>.jsonl[.gz]')
    parser.add_argument('--reviews', type=Path, required=True, help='Original <category>.jsonl[.gz]')
    parser.add_argument('--output', type=Path, required=True, help='New output directory for this category')
    parser.add_argument('--threads', type=int, default=None)
    parser.add_argument('--memory-limit', default='8GB')
    parser.add_argument('--ratios', type=float, nargs=3, default=(.8, .1, .1), metavar=('TRAIN', 'VALID', 'TEST'))
    args = parser.parse_args()
    try:
        prepare(**vars(args))
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f'Preparation failed: {error}\n')
    print('Prepared data:', args.output.resolve() / 'prepared.json')


if __name__ == '__main__':
    main()
