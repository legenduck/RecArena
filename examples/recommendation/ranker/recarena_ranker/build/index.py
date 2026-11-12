import argparse
import json
from pathlib import Path

from recarena_contracts.artifacts import make_manifest, write_json
from recarena_ranker.build.corpus import SearchCorpus
from ..internal import RetrievalConfig
from .lucene import build_index
from ..serve.retrieval import Retriever


def build(corpus_path: Path, output: Path):
    corpus = SearchCorpus.model_validate_json(corpus_path.read_text())
    if not corpus.documents or len({d.id for d in corpus.documents}) != len(corpus.documents):
        raise ValueError('Index corpus must have nonempty, unique parent products')
    output.mkdir(parents=True, exist_ok=False)
    documents = output / 'documents'
    documents.mkdir()
    with (documents / 'products.jsonl').open('x') as stream:
        for document in corpus.documents:
            stream.write(json.dumps(document.model_dump(), ensure_ascii=False) + '\n')
    build_index(documents, output / 'index')
    config = RetrievalConfig().model_dump(mode='json')
    write_json(output / 'index_config.json', {'catalog_snapshot_id': corpus.catalog_snapshot_id, 'retrieval': config})
    searcher = Retriever(output / 'index')
    if searcher.searcher.num_docs != len(corpus.documents):
        raise ValueError('Lucene document count does not match corpus')
    searcher.close()
    return make_manifest(output, 'lucene_index', config, sources=[corpus_path],
                         parents=[corpus.catalog_snapshot_id], counts={'products': len(corpus.documents)}, source_scope="examples/recommendation/ranker")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = build(args.corpus, args.output)
    print(manifest['artifact_id'])
