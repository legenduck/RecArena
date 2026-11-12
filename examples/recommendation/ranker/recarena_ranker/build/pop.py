"""Prepare timestamp-only public review data for the bundled pop policy."""
import argparse
import json
from pathlib import Path

import numpy as np
from recarena_contracts.artifacts import make_manifest, write_json
from ..timestamps import milliseconds


def write_reviews(items, item_rows, times, output, *, catalog_id, review_id, sources=()):
    """One entry per review; repeated reviewers/items are not deduplicated."""
    times = np.asarray(times, dtype=np.int64)
    item_rows = np.asarray(item_rows, dtype=np.int64)
    if times.shape != item_rows.shape or times.ndim != 1:
        raise ValueError('Invalid review timestamp columns')
    if len(set(items)) != len(items) or any(not isinstance(item, str) or not item for item in items):
        raise ValueError('Review products must be nonempty unique IDs')
    if len(item_rows) and (item_rows.min() < 0 or item_rows.max() >= len(items)):
        raise ValueError('Review product mapping mismatch')
    # Keep the supplied public-review timestamps; the serving policy applies tau.
    order = np.lexsort((times, item_rows))
    offsets = np.concatenate(([0], np.cumsum(np.bincount(item_rows, minlength=len(items)), dtype=np.int64)))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    np.save(output / 'timestamps_ms.npy', times[order], allow_pickle=False)
    np.save(output / 'offsets.npy', offsets, allow_pickle=False)
    write_json(output / 'product_id_to_row.json', {item: row for row, item in enumerate(items)})
    write_json(output / 'reference.json', {'catalog_snapshot_id': catalog_id, 'review_snapshot_id': review_id,
        'timestamp_unit': 'milliseconds'})
    return make_manifest(output, 'review_timestamps', {'basis': 'public_review_rows'},
        sources=list(sources), parents=[catalog_id, review_id], counts={'products': len(items), 'reviews': len(times)},
        source_scope='examples/recommendation/ranker')


def build(reviews_file, output, *, catalog_id, review_id, product_column='product_id', timestamp_column='timestamp_utc'):
    source = Path(reviews_file)
    if source.suffix == '.parquet':
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pq.read_table(source, columns=[product_column, timestamp_column]).combine_chunks()
        ids, timestamps = table.column(product_column).chunk(0), table.column(timestamp_column).chunk(0)
        if ids.null_count or timestamps.null_count or not pa.types.is_integer(timestamps.type):
            raise ValueError('Parquet input requires product IDs and non-null integer millisecond timestamps')
        encoded = ids.dictionary_encode()
        items, item_rows, times = encoded.dictionary.to_pylist(), encoded.indices.to_numpy(), timestamps.to_numpy()
    else:
        value = json.loads(source.read_text())
        rows = value['reviews'] if isinstance(value, dict) else value
        mapping = {}
        item_rows, times = [], []
        for review in rows:
            item = review[product_column]
            if item not in mapping:
                mapping[item] = len(mapping)
            item_rows.append(mapping[item])
            times.append(milliseconds(review[timestamp_column]))
        items = list(mapping)
    return write_reviews(items, item_rows, times, output, catalog_id=catalog_id, review_id=review_id,
                         sources=[source])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviews', type=Path, required=True, help='Prepared public reviews: Parquet or JSON reviews array')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--review-snapshot', required=True)
    parser.add_argument('--product-column', default='product_id')
    parser.add_argument('--timestamp-column', default='timestamp_utc', help='Parquet integers must be milliseconds')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.reviews, args.output, catalog_id=args.catalog, review_id=args.review_snapshot,
        product_column=args.product_column, timestamp_column=args.timestamp_column)
    print(json.dumps({'manifest_path': str((args.output/'manifest.json').resolve()), 'manifest': manifest}))


if __name__ == '__main__':
    main()
