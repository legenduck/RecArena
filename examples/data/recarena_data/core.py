"""Iterative 5-core on all ratings, with simultaneous user/item removal."""


def filter_core(connection, source, output):
    connection.execute('CREATE TEMP TABLE core_reviews AS SELECT * FROM read_parquet(?)', [str(source)])
    iterations = []
    try:
        while True:
            removed = connection.execute('''
                DELETE FROM core_reviews
                WHERE user_id IN (SELECT user_id FROM core_reviews GROUP BY user_id HAVING count(*) < 5)
                   OR parent_asin IN (SELECT parent_asin FROM core_reviews GROUP BY parent_asin HAVING count(*) < 5)
            ''').fetchone()[0]
            rows, users, items = connection.execute('SELECT count(*),count(DISTINCT user_id),'
                'count(DISTINCT parent_asin) FROM core_reviews').fetchone()
            iterations.append({'removed': removed, 'reviews': rows, 'users': users, 'items': items})
            if removed == 0:
                break
        connection.execute('COPY (SELECT * FROM core_reviews ORDER BY timestamp,user_id,parent_asin) '
            'TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(output)])
        return {'output': rows, 'users': users, 'items': items, 'iterations': iterations}
    finally:
        connection.execute('DROP TABLE core_reviews')
