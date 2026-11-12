"""Read-only adapter for published pre-policy-service records.

No files or algorithms are inspected here. These deterministic references must be
published by the provider before deploying the new API. New environments never
use index/model fields. Stored configuration and hashes are not changed.
"""
from .artifacts import canonical_hash


def project_sources(config, sources):
    result = {}
    for key, source in sources.items():
        if 'policy_id' in source['policy']:
            result[key] = source
            continue
        result[key] = {'policy_version_id': source['policy_version_id'], 'policy': {
            'service_id': 'default', 'family': source['policy']['family'],
            'policy_id': source['policy_version_id'], 'version': canonical_hash(config),
            'candidate_scope': canonical_hash({'index': config['index_artifact_id'], 'retrieval': config['retrieval']}),
            'candidate_limit': config['retrieval']['candidate_k']}}
    return result


def recorded_policy(config, source_id):
    if 'ranking_sources' in config:
        return config['ranking_sources'][source_id]['policy']
    return config['policy']


def recorded_artifacts(config):
    """Preserve historical export references, including unavailable metadata."""
    result = set()
    if 'index_artifact_id' in config:
        result.add(config['index_artifact_id'])
    result.update(config.get('artifact_ids', []))
    for source in config.get('ranking_sources', {}).values():
        result.update(source.get('artifact_ids', []))
    return result
