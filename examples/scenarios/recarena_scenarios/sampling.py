"""Deterministic eligibility and target selection, followed by seeded random sampling."""
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .sources import Sources

PRODUCT_FIELDS = ('title', 'store', 'price', 'main_category', 'categories', 'description',
                  'features', 'details', 'average_rating', 'rating_number')
REVIEW_COLUMNS = """{'rating':'DOUBLE','title':'VARCHAR','text':'VARCHAR','asin':'VARCHAR',
    'parent_asin':'VARCHAR','user_id':'VARCHAR','timestamp':'BIGINT',
    'helpful_vote':'BIGINT','verified_purchase':'BOOLEAN'}"""


def choose_users(eligible: list[str], count: int, seed: int) -> list[str]:
    if count < 1 or count > len(eligible):
        raise ValueError(f'Requested {count} users, but the eligible pool contains {len(eligible)}; no replacement')
    return sorted(random.Random(seed).sample(sorted(eligible), count))


def prepare_samples(sources: Sources, settings: dict, work: Path) -> tuple[list[dict], dict]:
    """Read raw reviews once; use the exact category arrays, not their display strings, for joins."""
    work.mkdir(parents=True, exist_ok=True)
    cfg = {'threads': settings['threads'], 'memory_limit': settings['memory_limit'],
           'temp_directory': str(work / '.spill'), 'preserve_insertion_order': False}
    with duckdb.connect(config=cfg) as con:
        def sql(statement, *values):
            return con.execute(statement, [str(v) if isinstance(v, Path) else v for v in values])

        sql('CREATE TABLE platform_history AS SELECT user_id, parent_asin, timestamp FROM read_parquet(?)',
            [str(sources.paths[k]) for k in ('train', 'valid')])
        if sql('SELECT count(*) FROM platform_history WHERE timestamp >= ? OR timestamp IS NULL', sources.t2).fetchone()[0]:
            raise ValueError('train/valid includes records at or after the fixed T2')
        sql('CREATE TABLE warm AS SELECT DISTINCT parent_asin FROM platform_history')
        print('Reading pre-T2 raw reviews for platform users...', flush=True)
        sql(f'''CREATE TABLE reviews AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (PARTITION BY user_id, parent_asin ORDER BY
                    timestamp, helpful_vote DESC, verified_purchase DESC, asin, rating, title, text) rn
                FROM read_json(?, format='newline_delimited', columns={REVIEW_COLUMNS})
                WHERE timestamp < ? AND user_id IN (SELECT user_id FROM platform_history)
            ) WHERE rn=1''', sources.paths['raw_reviews'], sources.t2)
        sql('''CREATE TABLE users AS SELECT user_id, count(*) n_total FROM reviews
               GROUP BY user_id HAVING count(*) >= ?''', settings['min_reviews'])
        if sql('''SELECT count(*) FROM platform_history v JOIN users USING (user_id)
            WHERE NOT EXISTS (SELECT 1 FROM reviews r WHERE r.user_id=v.user_id AND r.parent_asin=v.parent_asin)''').fetchone()[0]:
            raise ValueError('Original reviews do not cover the eligible users\' platform history')
        # Preserve original JSON product values for the selected sample; no metadata coercion here.
        sql('''CREATE TABLE meta AS SELECT parent_asin, categories AS path, json FROM (
            SELECT json_extract_string(json, '$.parent_asin') parent_asin,
                   from_json(json_extract(json, '$.categories'), '["VARCHAR"]') categories, json
            FROM read_json_objects(?, format='newline_delimited'))
            WHERE parent_asin IN (SELECT parent_asin FROM reviews)
               OR parent_asin IN (SELECT parent_asin FROM read_parquet(?))''',
            sources.paths['raw_metadata'], sources.paths['metadata'])
        if sql('SELECT count(*) FROM (SELECT parent_asin FROM meta GROUP BY 1 HAVING count(*) > 1)').fetchone()[0]:
            raise ValueError('Duplicate parent_asin in raw metadata; category identity is ambiguous')
        sql('''CREATE TABLE history AS SELECT r.*, CASE WHEN len(m.path)>0 THEN m.path END path
               FROM reviews r JOIN users USING (user_id) LEFT JOIN meta m USING (parent_asin)''')
        sql('''CREATE TABLE categories AS SELECT user_id, path, array_to_string(path, ' > ') path_str,
                  count(*) n_total
               FROM history GROUP BY user_id, path''')
        sql('''CREATE TABLE main AS SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY user_id ORDER BY
               (path IS NULL), n_total DESC, path_str, path) rn FROM categories
            ) WHERE rn=1 AND path IS NOT NULL AND n_total >= ?''', settings['min_category_reviews'])
        sql('''CREATE TABLE targets AS SELECT * EXCLUDE (rn) FROM (
            SELECT t.*, (w.parent_asin IS NULL) new_product,
                row_number() OVER (PARTITION BY t.user_id ORDER BY
                    (w.parent_asin IS NULL), t.timestamp, t.parent_asin) rn
            FROM read_parquet(?) t JOIN main c ON c.user_id=t.user_id
            JOIN read_parquet(?) catalog ON catalog.parent_asin=t.parent_asin
                 AND from_json(json_extract(catalog.json, '$.categories'), '["VARCHAR"]')=c.path
            LEFT JOIN warm w ON w.parent_asin=t.parent_asin
            WHERE t.timestamp >= ? AND t.rating >= ? AND (? OR w.parent_asin IS NOT NULL)
            ) WHERE rn=1''', sources.paths['test'], sources.paths['metadata'], sources.t2,
            settings['target_min_rating'], settings['allow_new_targets'])
        eligible = [r[0] for r in sql('SELECT user_id FROM targets ORDER BY user_id').fetchall()]
        sql('COPY (SELECT m.*, t.parent_asin target_parent_asin, t.new_product FROM main m JOIN targets t USING (user_id) ORDER BY user_id) TO ? (FORMAT parquet)', work / 'candidates.parquet')
        users = choose_users(eligible, settings['sample_size'], settings['seed'])
        con.execute('CREATE TABLE selected (user_id VARCHAR)')
        con.executemany('INSERT INTO selected VALUES (?)', [(u,) for u in users])
        paths = dict(sql('SELECT user_id, path_str FROM main JOIN selected USING (user_id)').fetchall())
        exact_paths = dict(sql('SELECT user_id, path FROM main JOIN selected USING (user_id)').fetchall())
        rows = sql('''SELECT h.user_id, h.timestamp, h.parent_asin, h.rating, h.title, h.text
            FROM history h JOIN main m ON h.user_id=m.user_id AND h.path=m.path
            JOIN selected s ON h.user_id=s.user_id ORDER BY h.user_id, h.timestamp, h.parent_asin''').fetchall()
        targets = sql('''SELECT user_id, timestamp, parent_asin, rating, title, text, new_product
            FROM targets JOIN selected USING (user_id) ORDER BY user_id''').fetchall()
        wanted = {r[2] for r in rows + targets}
        con.execute('CREATE TABLE wanted (parent_asin VARCHAR)')
        con.executemany('INSERT INTO wanted VALUES (?)', [(p,) for p in sorted(wanted)])
        products = {}
        for asin, raw in sql('SELECT parent_asin, json FROM meta JOIN wanted USING (parent_asin)').fetchall():
            product = json.loads(raw)
            products[asin] = {key: product.get(key) for key in PRODUCT_FIELDS}
        if wanted - products.keys():
            raise ValueError('Selected history contains products missing from raw metadata')

        def review(row):
            def clean(value):
                return re.sub(r'<br\s*/?>', '\n', value, flags=re.I).strip() if value is not None else None
            return {'date': datetime.fromtimestamp(row[1] / 1000, timezone.utc).strftime('%Y-%m-%d'),
                    'parent_asin': row[2], 'rating': row[3], 'review_title': clean(row[4]),
                    'review_text': clean(row[5]), 'product': products[row[2]]}

        samples = {uid: {'user_id': uid, 'main_category': paths[uid], 'reviews': []}
                   for uid in users}
        for row in rows:
            samples[row[0]]['reviews'].append(review(row))
        for row in targets:
            samples[row[0]]['target'] = {**review(row), 'new_product': row[6]}
        audit = {'eligible_users': len(eligible), 'selected_users': users, 'category_paths': exact_paths,
                 'T2': sources.t2, 'timestamp_unit': 'milliseconds',
                 'sampling': 'uniform_without_replacement', 'seed': settings['seed'],
                 'raw_reviews_before_T2': sql('SELECT count(*) FROM reviews').fetchone()[0]}
        return [samples[uid] for uid in users], audit
