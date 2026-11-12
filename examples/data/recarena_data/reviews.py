"""Review selection, chronology and one earliest review per user/product pair."""

REVIEW_COLUMNS = """{
    'rating':'DOUBLE', 'title':'VARCHAR', 'text':'VARCHAR', 'images':'JSON',
    'asin':'VARCHAR', 'parent_asin':'VARCHAR', 'user_id':'VARCHAR',
    'timestamp':'BIGINT', 'helpful_vote':'BIGINT', 'verified_purchase':'BOOLEAN'
}"""


def filter_reviews(connection, source, metadata, output):
    total = connection.execute("SELECT count(*) FROM read_json(?, format='newline_delimited', "
        "columns={'parent_asin':'VARCHAR'})", [str(source)]).fetchone()[0]
    kept = connection.execute(f"""
        COPY (SELECT * FROM read_json($source, format='newline_delimited', columns={REVIEW_COLUMNS})
              WHERE parent_asin IN (SELECT parent_asin FROM read_parquet($metadata)))
        TO $output (FORMAT PARQUET, COMPRESSION ZSTD)
    """, {'source': str(source), 'metadata': str(metadata), 'output': str(output)}).fetchone()[0]
    return {'input': total, 'output': kept}


def sort_reviews(connection, source, output):
    count = connection.execute('COPY (SELECT * FROM read_parquet($source) ORDER BY timestamp,user_id,parent_asin) '
        'TO $output (FORMAT PARQUET, COMPRESSION ZSTD)', {'source': str(source), 'output': str(output)}).fetchone()[0]
    return {'output': count}


def deduplicate_reviews(connection, source, output):
    count = connection.execute('''
        COPY (SELECT * FROM read_parquet($source)
              QUALIFY row_number() OVER (
                  PARTITION BY user_id,parent_asin ORDER BY timestamp,asin,text
              ) = 1
              ORDER BY timestamp,user_id,parent_asin)
        TO $output (FORMAT PARQUET, COMPRESSION ZSTD)
    ''', {'source': str(source), 'output': str(output)}).fetchone()[0]
    return {'output': count}
