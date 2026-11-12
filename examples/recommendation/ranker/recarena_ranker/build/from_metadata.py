"""Prepare the existing BM25 product projection from supplied metadata, without a DB cutover."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile

import duckdb

from recarena_contracts.artifacts import digest, provenance, write_json
from recarena_ranker.build.corpus import SearchCorpus
from recarena_data.provided_catalog import map_product
from recarena_ranker.build.corpus import PROJECTION_VERSION, search_document


def prepare(metadata: Path, output: Path, catalog_id: str):
    metadata = metadata.resolve(strict=True)
    SearchCorpus(catalog_snapshot_id=catalog_id, documents=())
    source_hash = digest(metadata)
    output.mkdir(parents=True, exist_ok=False)
    counts = Counter(metadata_products=0, indexed_products=0, indexed_without_price=0, excluded_products=0)
    reasons = Counter()
    seen = set()
    corpus_path = output / 'corpus.json'
    with tempfile.TemporaryDirectory(prefix='recarena-bm25-') as temporary:
        con = duckdb.connect(config={'threads':2,
            'memory_limit':os.environ.get('RECARENA_DATA_MEMORY_LIMIT', '1GB'), 'temp_directory':temporary})
        try:
            rows = con.execute('SELECT parent_asin,json FROM read_parquet(?) ORDER BY parent_asin', [str(metadata)])
            with corpus_path.open('x') as corpus, (output / 'excluded_products.jsonl').open('x') as excluded:
                corpus.write('{"catalog_snapshot_id":'+json.dumps(catalog_id)+',"documents":[')
                while batch := rows.fetchmany(2048):
                    for parent, raw in batch:
                        if parent in seen:
                            raise ValueError('Duplicate metadata parent ID')
                        seen.add(parent)
                        counts['metadata_products'] += 1
                        # Images, public ratings and history do not enter the BM25 text.
                        # These in-memory objects are never imported as a catalog.
                        product, variant, _ = map_product(parent, json.loads(raw), catalog_id=catalog_id,
                            images=[], review_count=0, rating=None)
                        document = search_document(product, [variant])
                        if document is None:
                            counts['excluded_products'] += 1
                            rejected = variant.provenance['excluded_from_purchase_reasons']
                            reasons.update(rejected)
                            excluded.write(json.dumps({'product_id':parent, 'reasons':rejected})+'\n')
                            continue
                        if counts['indexed_products']:
                            corpus.write(',')
                        corpus.write(document.model_dump_json())
                        counts['indexed_products'] += 1
                        counts['indexed_without_price'] += int(variant.unit_price_minor is None)
                corpus.write(']}\n')
        finally:
            con.close()
    if not counts['indexed_products']:
        raise ValueError('Prepared BM25 corpus is empty')
    if digest(metadata) != source_hash:
        raise ValueError('Source metadata changed during preparation')
    report = {'mode':'bm25_metadata_only', 'catalog_snapshot_id':catalog_id,
        'source':{'path':str(metadata), 'sha256':source_hash},
        'corpus':{'path':str(corpus_path.resolve()), 'sha256':digest(corpus_path)},
        'code_provenance':provenance("examples/data"), 'counts':dict(counts), 'exclusion_reasons':dict(reasons),
        'projection':'recarena_ranker.build.corpus.search_document', 'projection_version':PROJECTION_VERSION,
        'review_text_indexed':False, 'database_modified':False, 'source_data_modified':False,
        'model_prepared':False, 'catalog_registered':False}
    write_json(output / 'preparation_report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.metadata, args.output, args.catalog), ensure_ascii=False))
