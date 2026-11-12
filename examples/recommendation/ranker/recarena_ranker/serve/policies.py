"""The four specified ranking families. They only reorder an input CandidateSet."""
from dataclasses import dataclass

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from recarena_ranker.config import PolicyFamily
from ..internal import CandidateSet, RankedItem, RankedResult


from ..config import IMPLEMENTATIONS, PROFILE_IMPLEMENTATION, CF_IMPLEMENTATION, PolicyConfig


class PolicyFailure(ValueError):
    pass


@dataclass(frozen=True)
class PolicyDefinition:
    family: PolicyFamily
    description: str
    required_artifacts: tuple[str, ...]
    supports_user_context: bool

    def validate_config(self, config, user, catalog_id, artifacts, history_fingerprint=None):
        if config.family != self.family:
            raise PolicyFailure('Policy family mismatch')
        return validate_config(config, user, catalog_id, artifacts, history_fingerprint)

    def rank(self, candidates, user, config, version_id, artifacts):
        if config.family != self.family:
            raise PolicyFailure('Policy family mismatch')
        return rank(candidates, user, config, version_id, artifacts)

    def metadata(self):
        fields = PolicyConfig.model_json_schema()['properties']
        names = {
            'relevance': [], 'popularity': ['delta_t', 'tau'],
            'personalization': ['weight', 'combination', 'allow_unknown_user_fallback'],
            'diversity': ['weight', 'mmr_relevance_weight', 'base_policy'],
        }[self.family.value]
        return {'family': self.family.value, 'implementation_id': IMPLEMENTATIONS[self.family], 'version': '1.0',
                'description': self.description, 'required_artifacts': self.required_artifacts,
                'supports_user_context': self.supports_user_context,
                'parameter_schema': {'type': 'object', 'additionalProperties': False,
                                     'properties': {name: fields[name] for name in names}}}


REGISTRY = {
    PolicyFamily.relevance: PolicyDefinition(PolicyFamily.relevance, 'Lucene BM25 relevance', (), False),
    PolicyFamily.popularity: PolicyDefinition(PolicyFamily.popularity, 'BM25 candidates reordered by public review count before tau, cumulative or windowed', ('review_timestamps',), False),
    PolicyFamily.personalization: PolicyDefinition(PolicyFamily.personalization, 'BM25 plus offline RecBole BPR factors', ('bpr_serving',), True),
    PolicyFamily.diversity: PolicyDefinition(PolicyFamily.diversity, 'BM25 relevance with TF-IDF cosine MMR', ('tfidf',), False),
}


def required_artifacts(config):
    if config.implementation_id == CF_IMPLEMENTATION:
        return ('cf_serving',)
    if config.implementation_id == PROFILE_IMPLEMENTATION:
        return ('profile_scores',)
    if config.family == PolicyFamily.diversity and config.base_policy == 'personalization':
        return ('bpr_serving', 'tfidf')
    return REGISTRY[config.family].required_artifacts


def validate_config(config, user, catalog_id, artifacts, history_fingerprint=None):
    config = PolicyConfig.model_validate(config.model_dump(mode='json'))
    if config.family == PolicyFamily.diversity and config.allow_unknown_user_fallback:
        raise PolicyFailure('Diversity requires supported users for its personalization base')
    for kind in required_artifacts(config):
        if kind not in artifacts:
            raise PolicyFailure(f'ARTIFACT_NOT_READY: {kind}')
        item = artifacts[kind]
        parents = item.manifest['parent_artifact_ids']
        if kind == 'review_timestamps':
            if len(parents) != 2 or parents[0] != catalog_id:
                raise PolicyFailure('ARTIFACT_MISMATCH: public review catalog')
            continue
        expected = {'tfidf': [catalog_id], 'profile_scores': [catalog_id],
                    'bpr_serving': [catalog_id, user.history_snapshot_id],
                    'cf_serving': [catalog_id, user.history_snapshot_id]}[kind]
        lineage_matches = (parents[:2] == expected and len(parents) in (2, 3)) if kind in ('bpr_serving', 'cf_serving') else parents == expected
        if not lineage_matches:
            raise PolicyFailure('ARTIFACT_MISMATCH: lineage')
        if kind in ('bpr_serving', 'cf_serving') and history_fingerprint is not None:
            if item.history_fingerprint != history_fingerprint:
                raise PolicyFailure('ARTIFACT_MISMATCH: actual training history differs')
    if config.implementation_id == PROFILE_IMPLEMENTATION and user.user_id not in artifacts['profile_scores'].supported_users:
        raise PolicyFailure('unknown_user: user has no prepared profile scores')
    factor_kind = 'cf_serving' if config.implementation_id == CF_IMPLEMENTATION else 'bpr_serving'
    if factor_kind in required_artifacts(config) and user.user_id not in artifacts[factor_kind].trained_users:
        if config.family != PolicyFamily.personalization or not config.allow_unknown_user_fallback:
            raise PolicyFailure('unknown_user: user has no training support')
    return config


def normalize(values):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise PolicyFailure('Non-finite signal')
    if len(values) == 0:
        return values, False
    with np.errstate(over='raise', invalid='raise'):
        try:
            span = float(values.max() - values.min())
        except FloatingPointError as error:
            raise PolicyFailure('Signal normalization overflow') from error
    if span <= 1e-12:
        return np.zeros_like(values), True
    normalized = (values - values.min()) / span
    if not np.isfinite(normalized).all():
        raise PolicyFailure('Invalid normalized signal')
    return normalized, False


def mmr_order(base, candidates, candidate_features, weight):
    """Only K candidate rows are used; no full-catalog pair matrix is built."""
    base = np.asarray(base, dtype=np.float64)
    if len(base) != len(candidates) or not np.isfinite(base).all() or not 0 <= weight <= 1:
        raise PolicyFailure('Invalid MMR input')
    if candidate_features.shape[0] != len(base):
        raise PolicyFailure('Candidate feature mismatch')
    similarities = None
    if len(base) > 1 and candidate_features.shape[1]:
        similarities = cosine_similarity(candidate_features).astype(np.float64)
        if not np.isfinite(similarities).all():
            raise PolicyFailure('Invalid cosine similarity')
    remaining = set(range(len(candidates)))
    penalties = np.zeros(len(base), dtype=np.float64)
    chosen = []
    while remaining:
        scores = weight * base - (1 - weight) * penalties
        selected = min(remaining, key=lambda i: (-scores[i], -candidates[i].bm25_score, candidates[i].product_id))
        chosen.append((selected, float(scores[selected]), float(penalties[selected])))
        remaining.remove(selected)
        if remaining and similarities is not None:
            penalties = np.maximum(penalties, similarities[:, selected])
    return chosen


def personalized_base(relevance_scores, raw_scores, weight):
    combined = np.asarray(relevance_scores, dtype=np.float64).copy()
    supported = [i for i, value in enumerate(raw_scores) if value is not None]
    normalized = [None] * len(raw_scores)
    signal, constant = normalize([raw_scores[i] for i in supported])
    constant = constant or len(supported) <= 1
    for index, value in zip(supported, signal):
        normalized[index] = float(value)
        if not constant:
            combined[index] = (1 - weight) * combined[index] + weight * value
    return combined, normalized, constant


def personalized_rank_base(candidates, raw_scores, weight):
    """Fuse one-based BM25/BPR ranks with reciprocal log2 discounts."""
    supported = [i for i, value in enumerate(raw_scores) if value is not None]
    signal, constant = normalize([raw_scores[i] for i in supported])
    constant = constant or len(supported) <= 1
    query_signal = np.asarray([1 / np.log2(c.retrieval_rank + 1) for c in candidates], dtype=np.float64)
    combined = query_signal.copy()
    components = [{'bm25_rank': c.retrieval_rank, 'bm25_rank_discount': float(query_signal[i]),
                   'bpr_rank': None, 'bpr_rank_discount': None, 'bpr_raw': raw_scores[i],
                   'bpr_normalized': None} for i, c in enumerate(candidates)]
    for i, normalized in zip(supported, signal):
        components[i]['bpr_normalized'] = float(normalized)
    ordered = sorted(supported, key=lambda i: (-raw_scores[i], -candidates[i].bm25_score, candidates[i].product_id))
    for position, i in enumerate(ordered, 1):
        discount = float(1 / np.log2(position + 1))
        components[i].update(bpr_rank=position, bpr_rank_discount=discount)
        if not constant:
            combined[i] = (1 - weight) * query_signal[i] + weight * discount
    return combined, components, constant


def rank(candidates: CandidateSet, user, config: PolicyConfig, version_id, artifacts):
    config = validate_config(config, user, candidates.catalog_snapshot_id, artifacts)
    if config.implementation_id == PROFILE_IMPLEMENTATION:
        return rank_profile(candidates, user, version_id, artifacts['profile_scores'])
    if config.family == PolicyFamily.popularity:
        return rank_pop(candidates, config, version_id, artifacts['review_timestamps'])
    if config.family == PolicyFamily.personalization and config.combination in ('bpr', 'cf'):
        return rank_factors(candidates, user, config, version_id, artifacts)
    ids = [c.product_id for c in candidates.candidates]
    baseline, relevance_constant = normalize([c.bm25_score for c in candidates.candidates])
    base = baseline.copy()
    components = []
    flags = [{} for _ in ids]
    for candidate, score in zip(candidates.candidates, baseline):
        values = {key: None for key in ('bpr_raw', 'bpr_normalized', 'mmr_max_similarity', 'mmr_selection_score')}
        values.update(bm25_raw=candidate.bm25_score, relevance_normalized=float(score), base_score=float(score))
        components.append(values)
    diagnostics = {'requested_policy': config.family.value, 'effective_policy': config.family.value,
                   'constant_signal': False, 'relevance_constant': relevance_constant, 'fallback_reason': None}
    used = [artifacts[k].manifest['artifact_id'] for k in required_artifacts(config)]
    personal = config.family == PolicyFamily.personalization or (config.family == PolicyFamily.diversity and config.base_policy == 'personalization')
    if personal:
        scorer = artifacts['bpr_serving']
        if user.user_id not in scorer.trained_users:
            diagnostics.update(effective_policy='relevance', fallback_reason='unknown_user')
        else:
            raw = scorer.score(user.user_id, ids)
            if config.combination == 'log_rank':
                base, rank_components, constant = personalized_rank_base(
                    candidates.candidates, [raw[i] for i in ids], config.weight)
                for values, extra in zip(components, rank_components):
                    values.update(extra)
                diagnostics['personalization_combination'] = 'log_rank'
            else:
                base, signal, constant = personalized_base(baseline, [raw[i] for i in ids], config.weight)
                for index, score in enumerate(signal):
                    components[index].update(bpr_raw=raw[ids[index]], bpr_normalized=score)
            diagnostics['constant_signal'] = constant
            for i in range(len(ids)):
                flags[i]['bpr_untrained_item'] = raw[ids[i]] is None
    for index in range(len(ids)):
        components[index]['base_score'] = float(base[index])
    if config.family == PolicyFamily.diversity:
        features = artifacts['tfidf'].candidate_rows(ids)
        selection = mmr_order(base, candidates.candidates, features, config.mmr_relevance_weight)
    else:
        order = sorted(range(len(ids)), key=lambda i: (-base[i], -candidates.candidates[i].bm25_score, ids[i]))
        selection = [(i, float(base[i]), None) for i in order]
    result = []
    for final_rank, (i, score, penalty) in enumerate(selection, 1):
        if penalty is not None:
            components[i].update(mmr_max_similarity=penalty, mmr_selection_score=score)
        result.append(RankedItem(product_id=ids[i], retrieval_rank=candidates.candidates[i].retrieval_rank,
            final_rank=final_rank, final_score=score, score_components=components[i], signal_missing_flags=flags[i]))
    return RankedResult(candidate_set_id=candidates.candidate_set_id, policy_version_id=version_id,
        model_artifact_ids=used, ranked_items=result, diagnostics=diagnostics).validate_candidates(candidates)


def relevance(candidates, version_id):
    from recarena_contracts.models import UserContext
    return rank(candidates, UserContext(user_id='unused', history_snapshot_id='unused'),
                PolicyConfig(family='relevance', implementation_id='lucene_bm25_v1'), version_id, {})


def rank_profile(candidates, user, version_id, scorer):
    rows = candidates.candidates
    raw = scorer.score(user.user_id, [item.product_id for item in rows])
    if any(raw[item.product_id] is None or not np.isfinite(raw[item.product_id]) for item in rows):
        raise PolicyFailure('Invalid profile similarity')
    ordered = sorted(rows, key=lambda item: (-raw[item.product_id], -item.bm25_score, item.product_id))
    return RankedResult(candidate_set_id=candidates.candidate_set_id, policy_version_id=version_id,
        model_artifact_ids=[scorer.manifest['artifact_id']], ranked_items=[
            RankedItem(product_id=item.product_id, retrieval_rank=item.retrieval_rank, final_rank=position,
                final_score=raw[item.product_id],
                score_components={'bm25_raw':item.bm25_score, 'profile_similarity':raw[item.product_id],
                                  'base_score':raw[item.product_id]})
            for position,item in enumerate(ordered,1)], diagnostics={
                'requested_policy':'personalization', 'effective_policy':'personalization',
                'policy_name':'profile', 'score_source':'profile_tfidf_cosine',
                'constant_signal':len({raw[item.product_id] for item in rows})<=1,
                'fallback_reason':None, 'tie_break':'bm25_score_then_product_id',
            }).validate_candidates(candidates)


def rank_factors(candidates, user, config, version_id, artifacts):
    generic = config.implementation_id == CF_IMPLEMENTATION
    scorer = artifacts['cf_serving' if generic else 'bpr_serving']
    prefix = 'cf' if generic else 'bpr'
    if user.user_id not in scorer.trained_users:
        # Preserve the existing explicit unknown-user fallback option.
        if generic:
            result = relevance(candidates, version_id)
            return result.model_copy(update={'model_artifact_ids': [scorer.manifest['artifact_id']], 'diagnostics': {
                **result.diagnostics, 'requested_policy': 'personalization', 'effective_policy': 'relevance',
                'fallback_reason': 'unknown_user', 'personalization_combination': 'cf', 'model': scorer.model_name}})
        result = rank(candidates, user, config.model_copy(update={'combination': 'minmax'}), version_id, artifacts)
        return result.model_copy(update={'diagnostics': {
            **result.diagnostics, 'personalization_combination': 'bpr'}})
    rows = candidates.candidates
    raw = scorer.score(user.user_id, [item.product_id for item in rows])
    supported = [item for item in rows if raw[item.product_id] is not None]
    if any(not np.isfinite(raw[item.product_id]) for item in supported):
        raise PolicyFailure('Non-finite CF score' if generic else 'Non-finite BPR score')
    supported.sort(key=lambda item: (-raw[item.product_id], -item.bm25_score, item.product_id))
    missing = sorted((item for item in rows if raw[item.product_id] is None), key=lambda item: item.retrieval_rank)
    return RankedResult(candidate_set_id=candidates.candidate_set_id, policy_version_id=version_id,
        model_artifact_ids=[scorer.manifest['artifact_id']], ranked_items=[
            RankedItem(product_id=item.product_id, retrieval_rank=item.retrieval_rank, final_rank=position,
                final_score=raw[item.product_id],
                score_components={'bm25_raw': item.bm25_score, prefix + '_raw': raw[item.product_id],
                                  'base_score': raw[item.product_id]},
                signal_missing_flags={prefix + '_untrained_item': raw[item.product_id] is None})
            for position, item in enumerate(supported + missing, 1)], diagnostics={
                'requested_policy': 'personalization',
                'effective_policy': 'relevance' if rows and not supported else 'personalization',
                'personalization_combination': prefix,
                **({'model': scorer.model_name} if generic else {}),
                'constant_signal': len({raw[item.product_id] for item in supported}) <= 1,
                'fallback_reason': 'no_trained_candidate_items' if rows and not supported else None,
                'untrained_item_order': 'after_trained_bm25_order',
                'trained_candidate_count': len(supported), 'untrained_candidate_count': len(missing),
                'tie_break': 'bm25_score_then_product_id',
            }).validate_candidates(candidates)


def rank_pop(candidates, config, version_id, reviews):
    counts = reviews.counts([item.product_id for item in candidates.candidates], config.delta_t, config.tau)
    ordered = sorted(candidates.candidates, key=lambda item: (-counts[item.product_id], item.retrieval_rank))
    return RankedResult(candidate_set_id=candidates.candidate_set_id, policy_version_id=version_id,
        model_artifact_ids=[reviews.manifest['artifact_id']], ranked_items=[
            RankedItem(product_id=item.product_id, retrieval_rank=item.retrieval_rank, final_rank=position,
                final_score=float(counts[item.product_id]),
                score_components={'review_count': float(counts[item.product_id]), 'bm25_raw': item.bm25_score})
            for position, item in enumerate(ordered, 1)], diagnostics={
                'requested_policy': 'popularity', 'effective_policy': 'popularity', 'policy_name': 'pop',
                'count_basis': 'public_review_rows', 'delta_t_days': config.delta_t, 'tau': config.tau,
                'window': reviews.window(config.delta_t, config.tau), 'tie_break': 'bm25_order',
                'constant_signal': len(set(counts.values())) <= 1, 'fallback_reason': None,
            }).validate_candidates(candidates)
