from pathlib import Path

from recarena_contracts.artifacts import verify_manifest
from .factors import FactorScorer
from .features import TfidfArtifact
from .pop import RecentReviews
from .profile_scores import ProfileScores
from .policies import PolicyFailure


class ScoringArtifacts:
    def __init__(self, config):
        self.items = {}
        for key, kind in [('review_timestamps', 'review_timestamps'), ('tfidf', 'tfidf'), ('bpr', 'bpr_serving'), ('cf', 'cf_serving'), ('profile_scores', 'profile_scores')]:
            for filename in config.get(key, []):
                path = Path(filename)
                manifest = verify_manifest(path)
                if manifest['artifact_type'] != kind or manifest['artifact_id'] in self.items:
                    raise ValueError('Invalid/duplicate scoring artifact')
                if kind in ('bpr_serving', 'cf_serving'):
                    if len(manifest['parent_artifact_ids']) not in (2, 3):
                        raise ValueError('Invalid factor lineage')
                    item = FactorScorer(path.parent, catalog_id=manifest['parent_artifact_ids'][0], history_id=manifest['parent_artifact_ids'][1])
                elif kind == 'profile_scores':
                    item = ProfileScores(path.parent,manifest)
                else:
                    item = (RecentReviews if kind == 'review_timestamps' else TfidfArtifact)(path.parent)
                self.items[manifest['artifact_id']] = item

    def select(self, ids):
        result = {}
        for identifier in ids:
            if identifier not in self.items:
                raise PolicyFailure('ARTIFACT_NOT_READY: unknown artifact ID')
            item = self.items[identifier]
            kind = item.manifest['artifact_type']
            if kind in result:
                raise PolicyFailure('Ambiguous artifacts of the same type')
            result[kind] = item
        return result
