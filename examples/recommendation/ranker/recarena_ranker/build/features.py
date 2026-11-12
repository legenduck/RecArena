"""Offline TF-IDF artifact preparation."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from recarena_contracts.artifacts import make_manifest, write_json
from recarena_ranker.build.corpus import SearchCorpus

from ..feature_config import TFIDF_CONFIG


def build_tfidf(corpus_path: Path, output: Path):
    corpus = SearchCorpus.model_validate_json(corpus_path.read_text())
    if not corpus.documents or len({d.id for d in corpus.documents}) != len(corpus.documents):
        raise ValueError('TF-IDF requires a nonempty unique parent corpus')
    output.mkdir(parents=True, exist_ok=False)
    vectorizer = TfidfVectorizer(**(TFIDF_CONFIG | {'dtype': np.float32, 'ngram_range': (1, 2)}))
    try:
        matrix = vectorizer.fit_transform([d.contents for d in corpus.documents]).tocsr()
        vocabulary, idf = vectorizer.vocabulary_, vectorizer.idf_
    except ValueError as error:
        if 'empty vocabulary' not in str(error):
            raise
        # A corpus consisting entirely of filtered terms has genuine zero vectors.
        matrix = sparse.csr_matrix((len(corpus.documents), 0), dtype=np.float32)
        vocabulary, idf = {}, np.array([], dtype=np.float32)
    sparse.save_npz(output / 'matrix.npz', matrix)
    np.save(output / 'idf.npy', idf, allow_pickle=False)
    write_json(output / 'vocabulary.json', {k: int(v) for k, v in vocabulary.items()})
    write_json(output / 'item_id_to_row.json', {d.id: i for i, d in enumerate(corpus.documents)})
    write_json(output / 'vectorizer_config.json', TFIDF_CONFIG)
    return make_manifest(output, 'tfidf', TFIDF_CONFIG, sources=[corpus_path],
                         parents=[corpus.catalog_snapshot_id], counts={'products': matrix.shape[0], 'features': matrix.shape[1]}, source_scope="examples/recommendation/ranker")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['tfidf'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = build_tfidf(args.input, args.output)
    print(manifest['artifact_id'])
