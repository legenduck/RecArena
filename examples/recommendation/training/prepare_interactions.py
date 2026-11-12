"""Convert fixed time splits to RecBole input; no training or new split is performed."""
import argparse
import json
import os
from pathlib import Path
import re

import duckdb

SPLITS = ('train', 'valid', 'test')
OUTPUT_PARTS = {'train': ['train'], 'valid': ['valid'], 'test': ['test'], 'trainval': ['train', 'valid']}


def convert(*, dataset, output, prepared=None, split_dir=None, format='general', max_len=50,
            threads=None, memory_limit='8GB'):
    if bool(prepared) == bool(split_dir):
        raise ValueError('Supply either prepared.json or an existing split directory')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', dataset):
        raise ValueError('Dataset name must be a filename component using letters, digits, _, . or -')
    if format not in ('general', 'sequential') or max_len < 1:
        raise ValueError('Choose general or sequential format and a positive history length')
    threads = threads if threads is not None else (os.cpu_count() or 1)
    if threads < 1:
        raise ValueError('threads must be positive')
    cutoffs = None
    if prepared:
        prepared = Path(prepared).resolve(strict=True)
        document = json.loads(prepared.read_text())
        if document.get('format') != 'recarena-amazon-prepared-v1' or document.get('status') != 'complete':
            raise ValueError('Expected completed common preparation output')
        files = {name: (prepared.parent / document['files'][name]).resolve(strict=True) for name in SPLITS}
        cutoffs = document['time_split']
    else:
        files = {name: (Path(split_dir) / f'review_{name}.parquet').resolve(strict=True) for name in SPLITS}
    output = Path(output).resolve() / dataset
    output.mkdir(parents=True, exist_ok=False)
    report = {'format': format, 'dataset': dataset, 'timestamp_unit': 'milliseconds',
              'inputs': {name: str(path) for name, path in files.items()},
              'prepared': str(prepared) if prepared else None, 'time_split': cutoffs,
              'max_history': max_len if format == 'sequential' else None, 'counts': {}}
    with duckdb.connect(config={'threads': threads, 'memory_limit': memory_limit,
                                'temp_directory': str(output / '.spill'),
                                'preserve_insertion_order': False}) as connection:
        if format == 'sequential':
            parts = ' UNION ALL '.join(f"SELECT user_id,parent_asin,timestamp,'{name}' AS split "
                                      'FROM read_parquet(?)' for name in SPLITS)
            connection.execute(f'''
                CREATE TEMP TABLE sequences AS
                SELECT user_id,parent_asin,timestamp,split,
                       list(parent_asin) OVER (PARTITION BY user_id ORDER BY timestamp,parent_asin
                           ROWS BETWEEN {max_len} PRECEDING AND 1 PRECEDING) AS history
                FROM ({parts})
            ''', [str(files[name]) for name in SPLITS])
            report['sequence_rows'] = {name: {'input': total, 'without_history': empty}
                for name, total, empty in connection.execute('SELECT split,count(*),'
                    'count(*) FILTER (history IS NULL OR len(history)=0) FROM sequences GROUP BY split').fetchall()}
        for name, parts in OUTPUT_PARTS.items():
            destination = output / f'{dataset}.{name}.inter'
            if format == 'general':
                count = connection.execute('''
                    COPY (SELECT user_id AS "user_id:token", parent_asin AS "item_id:token",
                                 rating AS "rating:float", timestamp AS "timestamp:float"
                          FROM read_parquet($inputs) ORDER BY timestamp,user_id,parent_asin)
                    TO $output (FORMAT CSV, DELIMITER '\t', HEADER)
                ''', {'inputs': [str(files[p]) for p in parts], 'output': str(destination)}).fetchone()[0]
            else:
                count = connection.execute('''
                    COPY (SELECT user_id AS "user_id:token", array_to_string(history,' ') AS "item_id_list:token_seq",
                                 parent_asin AS "item_id:token", timestamp AS "timestamp:float"
                          FROM sequences WHERE split IN (SELECT unnest($parts)) AND len(history)>0
                          ORDER BY timestamp,user_id,parent_asin)
                    TO $output (FORMAT CSV, DELIMITER '\t', HEADER, QUOTE '')
                ''', {'parts': parts, 'output': str(destination)}).fetchone()[0]
            report['counts'][name] = count
            print(json.dumps({'split': name, 'rows': count, 'output': str(destination)}), flush=True)
    (output / 'conversion.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--prepared', type=Path, help='prepared.json from common preprocessing')
    source.add_argument('--split-dir', type=Path, help='Existing directory of review_{train,valid,test}.parquet')
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', type=Path, required=True, help='Parent of a new dataset directory')
    parser.add_argument('--format', choices=('general', 'sequential'), default='general')
    parser.add_argument('--max-len', type=int, default=50)
    parser.add_argument('--threads', type=int, default=None)
    parser.add_argument('--memory-limit', default='8GB')
    args = parser.parse_args()
    try:
        convert(**vars(args))
    except (ValueError, OSError, KeyError, duckdb.Error) as error:
        parser.exit(1, f'Interaction conversion failed: {error}\n')


if __name__ == '__main__':
    main()
