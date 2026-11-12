"""Read precomputed profile/item cosine scores owned by the bundled ranker."""
import json
from pathlib import Path
import numpy as np
from recarena_contracts.artifacts import verify_manifest


class ProfileScores:
    def __init__(self, directory: Path, manifest=None):
        self.manifest = manifest if manifest is not None else verify_manifest(directory/'manifest.json')
        if self.manifest['artifact_type'] != 'profile_scores' or len(self.manifest['parent_artifact_ids']) != 1:
            raise ValueError('Invalid profile score artifact')
        self.values = np.load(directory/'scores.npy', mmap_mode='r', allow_pickle=False)
        self.user_rows = json.loads((directory/'user_id_to_row.json').read_text())
        self.item_columns = json.loads((directory/'item_id_to_column.json').read_text())
        if self.values.ndim != 2 or self.values.dtype != np.float32:
            raise ValueError('Invalid profile score array')
        for mapping, length in zip((self.user_rows,self.item_columns),self.values.shape):
            if any(type(i) is not int for i in mapping.values()) or len(mapping)!=length or set(mapping.values())!=set(range(length)):
                raise ValueError('Profile score mapping mismatch')
        if self.values.shape != (self.manifest['counts']['users'],self.manifest['counts']['items']):
            raise ValueError('Profile score counts mismatch')
        self.supported_users = frozenset(self.user_rows)

    def score(self, user_id, product_ids):
        if user_id not in self.supported_users:
            raise ValueError('unknown_user: user has no prepared profile scores')
        if any(item not in self.item_columns for item in product_ids):
            raise ValueError('Profile scores missing candidate; artifact/catalog mismatch')
        values = self.values[self.user_rows[user_id], [self.item_columns[item] for item in product_ids]]
        if not np.isfinite(values).all() or (values<0).any() or (values>1+1e-5).any():
            raise ValueError('Invalid profile cosine scores')
        return dict(zip(product_ids,map(float,values)))
