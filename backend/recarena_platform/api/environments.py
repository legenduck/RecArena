"""HTTP environments boundary."""
import os
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_contracts.http import SiteSettingsRequest, PolicyValidationRequest, ControlPolicyRequest, PolicyDiagnosticRequest, RecommendationRequest, EnvironmentDraftRequest, EnvironmentLayoutRequest, EnvironmentValidationRequest
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import UserContext
from recarena_platform.db import runtime as db
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.environments import EnvironmentService, public_environment
from recarena_contracts.layout import from_environment
from recarena_platform.sessions import site_settings
from recarena_platform.api.dependencies import admin, outcome
from fastapi import APIRouter
router = APIRouter()


@router.get('/api/control/v1/policies', dependencies=[Depends(admin)])
def policy_definitions(request: Request):
    try:
        return {'request_id': request.state.request_id, 'policies': request.app.state.ranking.policies()}
    except RankingFailure:
        raise HTTPException(503, 'ARTIFACT_NOT_READY')


def policy_context(body, engine):
    with Session(engine) as session:
        env = session.get(db.EnvironmentVersion, body.environment_version_id)
        if env is None:
            raise HTTPException(404, 'RESULT_NOT_FOUND')
        config = env.config
        sources = from_environment(config).ranking_sources
        if body.source_id not in sources:
            raise HTTPException(422, 'INVALID_INPUT')
        source = sources[body.source_id]
        policy = body.policy or source.policy
        validation = PolicyValidationRequest(catalog_snapshot_id=env.dataset_snapshot_id,
            user=UserContext(user_id=body.user_id, history_snapshot_id=env.history_snapshot_id), policy=policy)
        return config, validation


@router.post('/api/control/v1/policies/validate', dependencies=[Depends(admin)])
def policy_validate(body: ControlPolicyRequest, request: Request):
    _, validation = policy_context(body, request.app.state.engine)
    try:
        request.app.state.ranking.validate_policy(validation)
    except RankingFailure:
        raise HTTPException(422, 'ARTIFACT_NOT_READY')
    return {'request_id': request.state.request_id, 'ready': True}


@router.post('/api/control/v1/policies/diagnostics', dependencies=[Depends(admin)])
def policy_diagnostics(body: PolicyDiagnosticRequest, request: Request):
    config, validation = policy_context(body, request.app.state.engine)
    try:
        request.app.state.ranking.validate_policy(validation)
        result = request.app.state.ranking.recommend(RecommendationRequest(query=body.query,
            catalog_snapshot_id=validation.catalog_snapshot_id, user=validation.user,
            policy=validation.policy, policy_version_id='diagnostic-' + canonical_hash(validation.policy.model_dump(mode='json'))))
        candidates, ranking = result.candidates, result.ranking
    except (ValueError, RankingFailure):
        raise HTTPException(503, 'POLICY_EXECUTION_FAILED')
    # Administrator diagnostics create no research Run or shopping-event denominator.
    return {'request_id': request.state.request_id, 'candidates': candidates, 'ranking': ranking}


@router.get('/api/control/v1/environments', dependencies=[Depends(admin)])
def environments(request: Request):
    with Session(request.app.state.engine) as session:
        return {'request_id':request.state.request_id, 'environments':[
            public_environment(e) for e in session.scalars(select(db.EnvironmentVersion).order_by(db.EnvironmentVersion.created_at))]}


@router.get('/api/control/v1/site-settings', dependencies=[Depends(admin)])
def get_site_settings(request: Request):
    with Session(request.app.state.engine) as session:
        return {'request_id':request.state.request_id, **site_settings(session),
            'shop_url':os.environ.get('RECARENA_SHOP_URL','http://127.0.0.1:5173').rstrip('/')+'/',
            'admin_url':os.environ.get('RECARENA_ADMIN_URL','http://127.0.0.1:5174').rstrip('/')+'/'}


@router.put('/api/control/v1/site-settings', dependencies=[Depends(admin)])
def put_site_settings(body: SiteSettingsRequest, request: Request):
    with Session(request.app.state.engine) as session,session.begin():
        identifiers = set(body.policies.values()) | ({body.default_environment_id} if body.default_environment_id else set())
        bases = set()
        for identifier in identifiers:
            env = session.get(db.EnvironmentVersion,identifier)
            if env is None or env.state!='PUBLISHED' or env.config_hash!=canonical_hash(env.config):
                raise HTTPException(422,'ARTIFACT_NOT_READY')
            from_environment(env.config)
            bases.add(canonical_hash({'catalog':env.dataset_snapshot_id,'history':env.history_snapshot_id,
                'reviews':env.review_snapshot_id,'candidate_scope':next(iter(from_environment(env.config).ranking_sources.values())).policy.candidate_scope}))
        if len(bases)>1:
            raise HTTPException(422,'CANDIDATE_ENVIRONMENT_MISMATCH')
        config=body.model_dump(mode='json')
        row=session.get(db.SiteSettings,'shop')
        if row: row.config=config
        else: session.add(db.SiteSettings(id='shop',config=config))
        session.add(db.OperatorAuditEvent(action='site_settings_changed',target_id='shop',document=config))
        return {'request_id':request.state.request_id,**config}


@router.get('/api/control/v1/environments/{environment_id}', dependencies=[Depends(admin)])
def environment(environment_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        value = session.get(db.EnvironmentVersion, environment_id)
        if value is None:
            raise HTTPException(404, 'RESULT_NOT_FOUND')
        return {'request_id':request.state.request_id, **public_environment(value)}


@router.post('/api/control/v1/environments', dependencies=[Depends(admin)])
def environment_draft(body: EnvironmentDraftRequest, request: Request):
    return outcome(request, EnvironmentService(request.app.state.engine, request.app.state.ranking).draft(body))


@router.put('/api/control/v1/environments/{environment_id}/layout', dependencies=[Depends(admin)])
def environment_layout(environment_id: str, body: EnvironmentLayoutRequest, request: Request):
    return outcome(request, EnvironmentService(request.app.state.engine, request.app.state.ranking).change(environment_id, 'layout', body))


@router.post('/api/control/v1/environments/{environment_id}/validate', dependencies=[Depends(admin)])
def environment_validate(environment_id: str, body: EnvironmentValidationRequest, request: Request):
    return outcome(request, EnvironmentService(request.app.state.engine, request.app.state.ranking).change(environment_id, 'validate', body))


@router.post('/api/control/v1/environments/{environment_id}/publish', dependencies=[Depends(admin)])
def environment_publish(environment_id: str, body: EnvironmentValidationRequest, request: Request):
    return outcome(request, EnvironmentService(request.app.state.engine, request.app.state.ranking).change(environment_id, 'publish', body))
