"""Fixed inference factors for BPR/LightGCN. No RecBole or checkpoint loading."""
import json
from pathlib import Path

import numpy as np
from recarena_contracts.artifacts import verify_manifest
from recarena_contracts.manifest import ArtifactManifest


class FactorScorer:
    def __init__(self, directory: Path, *, catalog_id: str, history_id: str):
        self.manifest = verify_manifest(directory / 'manifest.json')
        kind = self.manifest['artifact_type']
        if kind not in ('bpr_serving', 'cf_serving'):
            raise ValueError('Expected a serving factor artifact')
        if kind == 'cf_serving':
            metadata = json.loads((directory / 'model.json').read_text())
            representations = {'BPR': 'learned_embeddings', 'LightGCN': 'graph_propagated'}
            self.model_name = metadata.get('model')
            if (metadata.get('format') != 'recarena-cf-factors-v1' or metadata.get('score') != 'dot_product'
                    or self.model_name not in representations
                    or metadata.get('representation') != representations[self.model_name]):
                raise ValueError('Unsupported model or inference representation')
        else:
            self.model_name = 'BPR'
        parents = self.manifest['parent_artifact_ids']
        if len(parents) not in (2, 3) or parents[:2] != [catalog_id, history_id]:
            raise ValueError('ARTIFACT_MISMATCH: catalog/history lineage')
        self.training_artifact_id = None
        self.training_manifest = None
        if len(parents) == 3:
            training = ArtifactManifest.model_validate_json((directory / 'training_manifest.json').read_text())
            if training.artifact_type != ('cf_training' if kind == 'cf_serving' else 'bpr_training') or training.artifact_id != parents[2] or list(training.parent_artifact_ids) != parents[:2]:
                raise ValueError('ARTIFACT_MISMATCH: training lineage')
            self.training_artifact_id = training.artifact_id
            self.training_manifest = training.model_dump(mode='json')
        report = json.loads((directory / 'export_equivalence_report.json').read_text())
        self.quality_report = json.loads((directory / 'quality_report.json').read_text())
        if report.get('passed') is not True or report.get('sample_count', 0) < 1:
            raise ValueError('Export equivalence has not passed')
        self.user_factors = np.load(directory / 'user_factors.npy', mmap_mode='r', allow_pickle=False)
        self.item_factors = np.load(directory / 'item_factors.npy', mmap_mode='r', allow_pickle=False)
        self.user_rows = json.loads((directory / 'user_id_to_row.json').read_text())
        self.item_rows = json.loads((directory / 'item_id_to_row.json').read_text())
        self.trained_users = frozenset(json.loads((directory / 'trained_user_ids.json').read_text()))
        self.trained_items = frozenset(json.loads((directory / 'trained_item_ids.json').read_text()))
        history_file = directory / 'training_history.json'
        self.history_fingerprint = json.loads(history_file.read_text())['fingerprint'] if history_file.exists() else None
        for factors, mapping, support in [(self.user_factors, self.user_rows, self.trained_users),
                                           (self.item_factors, self.item_rows, self.trained_items)]:
            if factors.ndim != 2 or factors.dtype != np.float32 or factors.shape[1] < 1:
                raise ValueError('Invalid embedding shape/dtype')
            if any(type(row) is not int for row in mapping.values()) or set(mapping.values()) != set(range(len(factors))) or len(mapping) != len(factors):
                raise ValueError('Embedding row mapping mismatch')
            if not support.issubset(mapping) or not np.isfinite(factors).all() or '[PAD]' in mapping:
                raise ValueError('Invalid embedding support or values')
        if self.user_factors.shape[1] != self.item_factors.shape[1]:
            raise ValueError('Embedding dimension mismatch')
        if self.manifest['counts']['users'] != len(self.user_rows) or self.manifest['counts']['items'] != len(self.item_rows):
            raise ValueError('Embedding manifest counts mismatch')

    def score(self, user_id: str, product_ids: list[str]) -> dict[str, float | None]:
        if user_id not in self.trained_users:
            raise ValueError('unknown_user: user has no training support')
        result = dict.fromkeys(product_ids)
        supported = [item for item in result if item in self.trained_items]
        if supported:
            user = self.user_factors[self.user_rows[user_id]].astype(np.float64)
            items = self.item_factors[[self.item_rows[item] for item in supported]].astype(np.float64)
            # Batch the independent dot products, retaining the float64 dot
            # reduction used by np.dot(user, row). Matrix-vector BLAS can use
            # a different reduction order and perturb otherwise tied scores.
            scores = np.vecdot(user, items)
            if not np.isfinite(scores).all():
                raise ValueError('Non-finite factor score')
            result.update(zip(supported, map(float, scores)))
        return result
