"""Layout editing uses the existing draft → validate → immutable publish lifecycle."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.http import PolicyValidationRequest
from recarena_contracts.layout import from_environment
from recarena_contracts.models import UserContext
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.catalog.history import fixed_history_fingerprint


def public_environment(environment):
    value = {key:getattr(environment,key) for key in ('id','state','dataset_snapshot_id','review_snapshot_id',
                                                    'history_snapshot_id','config','config_hash')}
    try:
        value['presentation'] = from_environment(environment.config).model_dump(mode='json')
    except (KeyError, ValueError):
        value['presentation'] = None
        value['configuration_error'] = 'Environment has no valid shopping presentation'
    return value


def with_presentation(config, presentation):
    result = deepcopy(config)
    for key in ('policy','policy_version_id','artifact_ids','main_page_size','index_artifact_id','retrieval'):
        result.pop(key, None)
    result['schema_version'] = '2.0'
    result.update(presentation.model_dump(mode='json'))
    return result


def register_policy_versions(session,presentation):
    configurations = {}
    for source in presentation.ranking_sources.values():
        value = source.policy.model_dump(mode='json')
        if source.policy_version_id in configurations and configurations[source.policy_version_id] != value:
            raise ValueError('Policy version ID has conflicting configurations')
        configurations[source.policy_version_id] = value
    pending = []
    for identifier,config in configurations.items():
        existing = session.get(db.PolicyVersion,identifier)
        if existing and (existing.config != config or existing.config_hash != canonical_hash(config)):
            raise ValueError('Policy version is immutable')
        if existing is None:
            pending.append(db.PolicyVersion(id=identifier,config=config,config_hash=canonical_hash(config)))
    session.add_all(pending)


def ensure_ready(session, ranking, environment, user_id, strict_user=True):
    config = environment.config
    if environment.config_hash != canonical_hash(config):
        raise ValueError('Environment content hash mismatch')
    presentation = from_environment(config)
    if session.get(catalog.HistoricalUser, (environment.history_snapshot_id, user_id)) is None:
        raise ValueError('User outside fixed history')
    from recarena_contracts.legacy_policy import recorded_policy
    for source_id, source in presentation.ranking_sources.items():
        stored = session.get(db.PolicyVersion, source.policy_version_id)
        expected = recorded_policy(config, source_id)
        if stored and (stored.config != expected or stored.config_hash != canonical_hash(expected)):
            raise ValueError('Policy version configuration mismatch')
        ranking.validate_policy(PolicyValidationRequest(catalog_snapshot_id=environment.dataset_snapshot_id,
            user=UserContext(user_id=user_id, history_snapshot_id=environment.history_snapshot_id),
            policy=source.policy, strict_user=strict_user))
    return presentation


class EnvironmentService:
    def __init__(self, engine, ranking):
        self.engine, self.ranking = engine, ranking

    def draft(self, body):
        with Session(self.engine) as session, session.begin():
            base = session.get(db.EnvironmentVersion, body.base_environment_id) if body.base_environment_id else None
            if body.base_environment_id and base is None:
                return rejected('RESULT_NOT_FOUND', 404)
            if base is None and (body.bindings is None or body.presentation is None):
                return rejected('INVALID_INPUT',422)
            try:
                config = with_presentation(base.config if base else {}, body.presentation or from_environment(base.config))
                # An old model configuration and a service binding are different records.
                for source in config['ranking_sources'].values():
                    stored = session.get(db.PolicyVersion, source['policy_version_id'])
                    if stored is not None and stored.config != source['policy']:
                        source['policy_version_id'] = str(uuid4())
                catalog_id,review_id,history_id = (base.dataset_snapshot_id,base.review_snapshot_id,base.history_snapshot_id) if base else (None,None,None)
                if body.bindings:
                    bindings = body.bindings
                    catalog_id,review_id,history_id = bindings.catalog_snapshot_id,bindings.review_snapshot_id,bindings.history_snapshot_id
                    history,review = session.get(catalog.HistorySnapshot,history_id),session.get(catalog.ReviewSnapshot,review_id)
                    if history is None or review is None or history.dataset_snapshot_id != catalog_id or review.dataset_snapshot_id != catalog_id:
                        return rejected('ARTIFACT_MISMATCH',422)
                    config.update(schema_version='2.0', history_fingerprint=fixed_history_fingerprint(session,history_id))
                from_environment(config)
            except (ValueError, KeyError):
                return rejected('INVALID_INPUT', 422)
            value = db.EnvironmentVersion(state='DRAFT', dataset_snapshot_id=catalog_id,
                review_snapshot_id=review_id, history_snapshot_id=history_id,
                config=config, config_hash=canonical_hash(config))
            session.add(value)
            session.flush()
            session.add(db.OperatorAuditEvent(action='environment_draft_created',target_id=value.id,
                document={'config_hash':value.config_hash,'base_environment_id':body.base_environment_id}))
            return Outcome(public_environment(value))

    def change(self, environment_id, action, body):
        with Session(self.engine) as session, session.begin():
            value = session.scalar(select(db.EnvironmentVersion).where(db.EnvironmentVersion.id == environment_id).with_for_update())
            if value is None:
                return rejected('RESULT_NOT_FOUND', 404)
            if value.state == 'PUBLISHED':
                return rejected('ENVIRONMENT_IMMUTABLE', 409)
            try:
                if action == 'layout':
                    config = with_presentation(value.config, body.presentation)
                    for source in config['ranking_sources'].values():
                        stored = session.get(db.PolicyVersion, source['policy_version_id'])
                        if stored is not None and 'policy_id' not in stored.config:
                            source['policy_version_id'] = str(uuid4())
                    from_environment(config)
                    value.config, value.config_hash, value.state = config, canonical_hash(config), 'DRAFT'
                else:
                    if action == 'publish' and value.state != 'VALIDATED':
                        return rejected('ENVIRONMENT_NOT_VALIDATED', 409)
                    ensure_ready(session, self.ranking, value, body.user_id)
                    register_policy_versions(session,from_environment(value.config))
                    value.state = 'PUBLISHED' if action == 'publish' else 'VALIDATED'
            except (ValueError, KeyError, RankingFailure):
                return rejected('INVALID_INPUT' if action == 'layout' else 'ARTIFACT_NOT_READY', 422)
            session.flush()
            session.add(db.OperatorAuditEvent(action='environment_'+action,target_id=value.id,document={'config_hash':value.config_hash}))
            return Outcome(public_environment(value))
