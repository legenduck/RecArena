"""Configured baseline policies. Index/model selection stays on this server."""
from decimal import Decimal
from pydantic import Field
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import Contract, ID, PolicyDefinition, PolicyConfig as PolicyReference
from .config import PolicyConfig, PROFILE_IMPLEMENTATION
from .internal import RetrievalConfig
from .timestamps import normalize_tau


class PolicyProfile(Contract):
    policy_id: ID
    version: ID
    name: str
    catalog_snapshot_id: ID
    index_artifact_id: ID
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    configuration: PolicyConfig
    artifact_ids: tuple[ID, ...] = ()

    @property
    def candidate_scope(self):
        return canonical_hash({'index': self.index_artifact_id, 'retrieval': self.retrieval.model_dump(mode='json')})

    def definition(self, service_id='default'):
        return PolicyDefinition(name=self.name, catalog_snapshot_id=self.catalog_snapshot_id,
            policy=PolicyReference(service_id=service_id, policy_id=self.policy_id, version=self.version,
                family=self.configuration.family, candidate_scope=self.candidate_scope,
                candidate_limit=self.retrieval.candidate_k))


def from_legacy_environment(environment):
    """One-time provider preparation; accepts exported historical settings, not a DB."""
    config = environment['config']
    sources = config.get('ranking_sources') or {'main': {'policy': config['policy'],
        'policy_version_id': config['policy_version_id'], 'artifact_ids': config.get('artifact_ids', [])}}
    return [PolicyProfile(policy_id=source['policy_version_id'], version=canonical_hash(config),
        name=f"{source['policy']['family']} · {environment['dataset_snapshot_id']}",
        catalog_snapshot_id=environment['dataset_snapshot_id'], index_artifact_id=config['index_artifact_id'],
        retrieval=config['retrieval'], configuration=source['policy'], artifact_ids=source.get('artifact_ids', []))
        for source in sources.values() if 'policy_id' not in source['policy']]


def environment_config(profile, layout, **metadata):
    """The optional preparation tools publish only the provider reference."""
    from uuid import uuid4
    return {'schema_version': '2.0', **metadata, 'ranking_sources': {'main': {
        'policy': profile.definition().policy.model_dump(mode='json'), 'policy_version_id': str(uuid4())}},
        'layout': layout}


def create_profile(*, policy_id, name, catalog_snapshot_id, index_artifact_id, configuration,
                   retrieval=None, artifact_ids=()):
    value = dict(policy_id=policy_id, name=name, catalog_snapshot_id=catalog_snapshot_id,
        index_artifact_id=index_artifact_id, configuration=configuration,
        retrieval=retrieval or RetrievalConfig().model_dump(mode='json'), artifact_ids=list(artifact_ids))
    profile = PolicyProfile(version='pending', **value)
    return profile.model_copy(update={'version': canonical_hash(profile.model_dump(mode='json', exclude={'version'}))})


def apply_startup_settings(profile, *, k=None, delta_t=None, tau=None, personal_lambda=None, div_lambda=None):
    """Changed settings are new identities, never a silent change to a pinned version."""
    retrieval = profile.retrieval.model_dump(mode='json')
    configuration = profile.configuration.model_dump(mode='json')
    if k is not None:
        retrieval['candidate_k'] = k
    if delta_t is not None and profile.configuration.family.value == 'popularity':
        configuration['delta_t'] = delta_t
    if tau is not None and profile.configuration.family.value == 'popularity':
        configuration['tau'] = normalize_tau(tau)
    family = profile.configuration.family.value
    if personal_lambda is not None and (family == 'personalization' or (
            family == 'diversity' and profile.configuration.base_policy == 'personalization')):
        # The public lambda is the query weight; existing stored weight is BPR.
        # Decimal preserves the existing 0.3 default exactly for lambda=0.7.
        if profile.configuration.implementation_id == PROFILE_IMPLEMENTATION:
            if personal_lambda != 0:
                raise ValueError('Profile reranking requires personal_lambda to be omitted or zero')
        elif profile.configuration.combination in ('bpr', 'cf'):
            if personal_lambda != 0:
                raise ValueError('Model-only ranking requires personal_lambda to be omitted or zero')
        else:
            configuration['weight'] = float(Decimal(1) - Decimal(str(personal_lambda)))
    if div_lambda is not None and family == 'diversity':
        configuration['mmr_relevance_weight'] = div_lambda
    if retrieval == profile.retrieval.model_dump(mode='json') and configuration == profile.configuration.model_dump(mode='json'):
        return profile
    return create_profile(policy_id=profile.policy_id, name=profile.name,
        catalog_snapshot_id=profile.catalog_snapshot_id, index_artifact_id=profile.index_artifact_id,
        retrieval=retrieval, configuration=configuration, artifact_ids=profile.artifact_ids)
