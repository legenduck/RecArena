"""One global pair of time cutoffs per input category; boundary ties stay together."""
from datetime import datetime, timezone
import math
from pathlib import Path


def normalize_ratios(ratios):
    if (len(ratios) != 3 or any(not math.isfinite(x) or x < 0 for x in ratios)
            or not math.isfinite(sum(ratios)) or sum(ratios) <= 0):
        raise ValueError('Supply three finite, nonnegative split ratios with a positive sum')
    total = sum(ratios)
    return tuple(x / total for x in ratios)


def split_by_time(connection, source, output, ratios=(.8, .1, .1)):
    ratios = normalize_ratios(ratios)
    output = Path(output)
    output.mkdir()
    connection.execute('CREATE TEMP TABLE split_reviews AS SELECT * FROM read_parquet(?)', [str(source)])
    try:
        count, missing = connection.execute('SELECT count(*),count(*) FILTER (timestamp IS NULL) '
            'FROM split_reviews').fetchone()
        if count == 0:
            raise ValueError('No reviews remain after 5-core; time cutoffs cannot be determined')
        if missing:
            raise ValueError('Reviews with no timestamp cannot be assigned to a time split')
        t1, t2 = connection.execute('SELECT quantile_disc(timestamp,?),quantile_disc(timestamp,?) '
            'FROM split_reviews', [ratios[0], ratios[0] + ratios[1]]).fetchone()
        conditions = {'train': ('timestamp < $t1', {'t1': t1}),
                      'valid': ('timestamp >= $t1 AND timestamp < $t2', {'t1': t1, 't2': t2}),
                      'test': ('timestamp >= $t2', {'t2': t2})}
        counts = {}
        for name, (where, parameters) in conditions.items():
            path = output / f'review_{name}.parquet'
            n = connection.execute(f'COPY (SELECT * FROM split_reviews WHERE {where} '
                'ORDER BY timestamp,user_id,parent_asin) TO $output (FORMAT PARQUET, COMPRESSION ZSTD)',
                {**parameters, 'output': str(path)}).fetchone()[0]
            counts[name] = n
        return {'timestamp_unit': 'milliseconds', 'timezone': 'UTC', 'ratios': list(ratios),
                'T1': t1, 'T2': t2,
                'T1_utc': datetime.fromtimestamp(t1 / 1000, timezone.utc).isoformat(),
                'T2_utc': datetime.fromtimestamp(t2 / 1000, timezone.utc).isoformat(),
                'rule': 'train < T1; T1 <= valid < T2; test >= T2',
                'method': 'quantile_disc', 'counts': counts}
    finally:
        connection.execute('DROP TABLE split_reviews')
