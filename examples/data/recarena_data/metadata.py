"""Select the Amazon catalog while preserving each original metadata record."""


def filter_metadata(connection, source, output):
    connection.execute("""
        CREATE TEMP TABLE metadata_filter AS
        SELECT json->>'$.parent_asin' AS parent_asin,
               json_type(json->'$.price') IN ('DOUBLE','BIGINT','UBIGINT') AS has_price,
               len(list_filter(
                   coalesce(from_json(json->'$.images',
                       '[{"hi_res":"VARCHAR","large":"VARCHAR","thumb":"VARCHAR"}]'), []),
                   image -> coalesce(image.hi_res, image.large, image.thumb) IS NOT NULL
               )) > 0 AS has_image,
               json
        FROM read_ndjson_objects(?)
    """, [str(source)])
    try:
        total, priced, kept = connection.execute('SELECT count(*), count(*) FILTER (has_price), '
            'count(*) FILTER (has_price AND has_image) FROM metadata_filter').fetchone()
        connection.execute('COPY (SELECT parent_asin,json FROM metadata_filter WHERE has_price AND has_image) '
            'TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(output)])
        return {'input': total, 'numeric_price': priced, 'output': kept}
    finally:
        connection.execute('DROP TABLE metadata_filter')


def select_catalog(connection, metadata, reviews, output):
    count = connection.execute('COPY (SELECT * FROM read_parquet($metadata) WHERE parent_asin IN '
        '(SELECT parent_asin FROM read_parquet($reviews))) TO $output (FORMAT PARQUET, COMPRESSION ZSTD)',
        {'metadata': str(metadata), 'reviews': str(reviews), 'output': str(output)}).fetchone()[0]
    return {'output': count}
