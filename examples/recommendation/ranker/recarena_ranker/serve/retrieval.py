"""The only search implementation: a long-lived Pyserini LuceneSearcher."""
import math
from pathlib import Path
from recarena_contracts.text import normalize_query


class Retriever:
    def __init__(self, index: Path, k1=1.2, b=.75):
        from pyserini.search.lucene import LuceneSearcher
        self.searcher = LuceneSearcher(str(index))
        self.searcher.set_bm25(k1, b)

    def retrieve(self, query: str, k: int = 200) -> list[dict]:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError('candidate_k must be a positive integer')
        hits = self.searcher.search(normalize_query(query), k=k)
        candidates = [{'product_id': hit.docid, 'bm25_score': float(hit.score)} for hit in hits]
        if any(not math.isfinite(c['bm25_score']) for c in candidates):
            raise ValueError('Lucene returned a non-finite score')
        candidates.sort(key=lambda c: (-c['bm25_score'], c['product_id']))
        for i, candidate in enumerate(candidates, 1):
            candidate['retrieval_rank'] = i
        return candidates

    def close(self):
        self.searcher.close()
