"""Load artifacts used by the bundled recommendation implementation."""
import json
from pathlib import Path
import numpy as np
from scipy import sparse
from recarena_contracts.artifacts import canonical_hash, verify_manifest
from ..feature_config import TFIDF_CONFIG


class TfidfArtifact:
    def __init__(self, directory: Path):
        self.manifest = verify_manifest(directory / 'manifest.json')
        if self.manifest['artifact_type'] != 'tfidf' or len(self.manifest['parent_artifact_ids']) != 1:
            raise ValueError('Invalid TF-IDF artifact')
        config = json.loads((directory / 'vectorizer_config.json').read_text())
        if config != TFIDF_CONFIG or canonical_hash(config) != self.manifest['config_hash']:
            raise ValueError('TF-IDF configuration mismatch')
        self.matrix = sparse.load_npz(directory / 'matrix.npz').tocsr()
        self.rows = json.loads((directory / 'item_id_to_row.json').read_text())
        if self.matrix.dtype != np.float32 or not np.isfinite(self.matrix.data).all() or (self.matrix.data < 0).any():
            raise ValueError('Invalid TF-IDF values')
        if any(type(row) is not int for row in self.rows.values()) or len(self.rows) != self.matrix.shape[0] or set(self.rows.values()) != set(range(self.matrix.shape[0])):
            raise ValueError('TF-IDF row mapping mismatch')
        if self.matrix.shape != (self.manifest['counts']['products'], self.manifest['counts']['features']):
            raise ValueError('TF-IDF manifest shape mismatch')
        vocabulary = json.loads((directory / 'vocabulary.json').read_text())
        idf = np.load(directory / 'idf.npy', allow_pickle=False)
        columns = self.matrix.shape[1]
        if (len(vocabulary) != columns or any(type(row) is not int for row in vocabulary.values())
                or set(vocabulary.values()) != set(range(columns)) or idf.shape != (columns,)
                or idf.dtype != np.float32 or not np.isfinite(idf).all() or (idf < 1).any()):
            raise ValueError('TF-IDF vocabulary/IDF mismatch')

    def candidate_rows(self, product_ids):
        if any(i not in self.rows for i in product_ids):
            raise ValueError('TF-IDF missing candidate; artifact/catalog mismatch')
        return self.matrix[[self.rows[i] for i in product_ids]].astype(np.float64)
