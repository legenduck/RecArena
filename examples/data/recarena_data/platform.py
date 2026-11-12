"""Prepare a platform catalog from common preprocessing outputs; no DB, model or server needed."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import duckdb

from recarena_contracts.artifacts import write_json
from .provided_catalog import publish_catalog


def prepare_platform(*, prepared, output, catalog_id, review_id, history_id,
                     image_manifest=None, threads=None, memory_limit='8GB'):
    prepared = Path(prepared).resolve(strict=True)
    document = json.loads(prepared.read_text())
    if document.get('format') != 'recarena-amazon-prepared-v1' or document.get('status') != 'complete':
        raise ValueError('Expected completed common preprocessing output (prepared.json)')
    t2 = document['time_split']['T2']
    if type(t2) is not int or document['time_split']['timestamp_unit'] != 'milliseconds':
        raise ValueError('T2 must be the prepared integer millisecond cutoff')
    cutoff = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=t2)
    files = {name: (prepared.parent / document['files'][name]).resolve(strict=True)
             for name in ('metadata', 'reviews_deduplicated', 'train', 'valid')}
    threads = threads if threads is not None else (os.cpu_count() or 1)
    if type(threads) is not int or threads < 1:
        raise ValueError('threads must be a positive integer')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    selected = output / 'review_platform.parquet'
    report = {'format': 'recarena-platform-prepared-v1', 'status': 'running',
              'prepared': str(prepared), 'category': document['category'],
              'inputs': {name: str(path) for name, path in files.items()},
              'T2': t2, 'T2_utc': cutoff.isoformat(),
              'selection': {'products': 'post_5core_metadata',
                            'reviews': 'pre_5core_deduplicated_reviews_for_catalog_items_before_T2',
                            'review_rating': 'finite rating between 1 and 5 inclusive',
                            'history': '5core_train_plus_valid', 'cutoff': 'timestamp < T2'},
              'settings': {'threads': threads, 'memory_limit': memory_limit}}
    current = 'public_reviews'
    try:
        with duckdb.connect(config={'threads': threads, 'memory_limit': memory_limit,
                                    'temp_directory': str(output / '.spill'),
                                    'preserve_insertion_order': False}) as connection:
            eligible, invalid = connection.execute('''
                SELECT count(*), count(*) FILTER (
                    WHERE r.rating IS NULL OR NOT isfinite(r.rating) OR r.rating NOT BETWEEN 1 AND 5)
                FROM read_parquet($reviews) r
                SEMI JOIN read_parquet($metadata) m USING (parent_asin)
                WHERE r.timestamp < $t2
            ''', {'reviews': str(files['reviews_deduplicated']), 'metadata': str(files['metadata']),
                  't2': t2}).fetchone()
            count = connection.execute('''
                COPY (SELECT r.* FROM read_parquet($reviews) r
                      SEMI JOIN read_parquet($metadata) m USING (parent_asin)
                      WHERE r.timestamp < $t2 AND isfinite(r.rating) AND r.rating BETWEEN 1 AND 5
                      ORDER BY r.timestamp,r.user_id,r.parent_asin)
                TO $output (FORMAT PARQUET, COMPRESSION ZSTD)
            ''', {'reviews': str(files['reviews_deduplicated']), 'metadata': str(files['metadata']),
                  't2': t2, 'output': str(selected)}).fetchone()[0]
        report['review_selection'] = {'eligible_before_rating_validation': eligible,
                                      'excluded_invalid_rating': invalid, 'selected': count}
        print(json.dumps({'stage': current, 'rows': count, 'exclusive_T2': t2,
                          **report['review_selection']}), flush=True)
        current = 'catalog_package'
        packaged = publish_catalog(metadata=files['metadata'], reviews=selected,
            history_parquets=[files['train'], files['valid']], review_cutoff=cutoff,
            image_manifest=image_manifest, output=output / 'catalog',
            catalog_id=catalog_id, review_id=review_id, history_id=history_id,
            threads=threads, memory_limit=memory_limit)
        report.update(status='complete', manifest_path=packaged['manifest_path'],
            counts=packaged['report']['counts'], history_fingerprint=packaged['report']['history_fingerprint'],
            image_delivery=packaged['report']['image_delivery'])
        write_json(output / 'platform.json', report)
        return report
    except Exception as error:
        report.update(status='failed', failed_stage=current, error=str(error))
        write_json(output / 'failed.json', report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--history', required=True)
    parser.add_argument('--image-manifest', type=Path, help='Optional registered local images; default uses metadata URLs')
    parser.add_argument('--threads', type=int)
    parser.add_argument('--memory-limit', default='8GB')
    args = parser.parse_args()
    try:
        report = prepare_platform(prepared=args.prepared, output=args.output,
            catalog_id=args.catalog, review_id=args.review, history_id=args.history,
            image_manifest=args.image_manifest, threads=args.threads, memory_limit=args.memory_limit)
    except (ValueError, OSError, KeyError, duckdb.Error) as error:
        parser.exit(1, f'Platform data preparation failed: {error}\n')
    print(json.dumps({'manifest_path': report['manifest_path'], 'counts': report['counts']}, allow_nan=False))


if __name__ == '__main__':
    main()
