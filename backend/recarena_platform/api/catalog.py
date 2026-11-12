"""HTTP catalog boundary."""
from fastapi import Depends, HTTPException, Query, Request
from psycopg import Error as PsycopgError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from recarena_contracts.http import PolicyValidationRequest
from recarena_contracts.models import UserContext
from recarena_platform.db import runtime as db
from recarena_platform.ranking_client import RankingFailure
from recarena_contracts.layout import from_environment
from recarena_contracts.admin import CatalogImportRequest, HistoryImportRequest
from recarena_platform.catalog.administration import AdminDataService
from recarena_platform.db import catalog as catalog
from recarena_platform.catalog.artifacts import ArtifactService, prepared_path
from recarena_platform.catalog.importing import import_catalog_file, ImmutableCatalog
from recarena_contracts.artifacts import digest
from recarena_platform.api.dependencies import admin, outcome
from fastapi import APIRouter
router = APIRouter()


@router.get('/api/control/v1/tasks', dependencies=[Depends(admin)])
def list_tasks(request: Request):
    with Session(request.app.state.engine) as session:
        return {'request_id':request.state.request_id,'tasks':[{'id':t.id,**t.document} for t in session.scalars(select(catalog.TaskVersion))]}


@router.get('/api/control/v1/users/{user_id}/history', dependencies=[Depends(admin)])
def user_history(user_id: str, history_snapshot_id: str, request: Request,
                 offset: int = Query(default=0,ge=0), limit: int = Query(default=20,ge=1,le=100)):
    with Session(request.app.state.engine) as session:
        if session.get(catalog.HistoricalUser,(history_snapshot_id,user_id)) is None:
            raise HTTPException(404,'UNKNOWN_USER')
        records=session.execute(select(catalog.HistoricalInteraction,catalog.Product).join(catalog.Product,
            (catalog.Product.dataset_snapshot_id==catalog.HistoricalInteraction.dataset_snapshot_id)&
            (catalog.Product.product_id==catalog.HistoricalInteraction.product_id)).where(
            catalog.HistoricalInteraction.history_snapshot_id==history_snapshot_id,
            catalog.HistoricalInteraction.user_id==user_id).order_by(
            catalog.HistoricalInteraction.timestamp_utc.desc(),catalog.HistoricalInteraction.product_id).offset(offset).limit(limit+1)).all()
        return {'request_id':request.state.request_id,'user_id':user_id,'history_snapshot_id':history_snapshot_id,
            'has_more':len(records)>limit,'interactions':[{'product_id':i.product_id,'title':p.document.get('title',i.product_id),
                'timestamp_utc':i.timestamp_utc,'interaction':i.document} for i,p in records[:limit]]}


@router.get('/api/control/v1/artifacts', dependencies=[Depends(admin)])
def list_artifacts(request: Request):
    return {'request_id':request.state.request_id,**ArtifactService(request.app.state.engine,request.app.state.ranking).list()}


@router.post('/api/control/v1/users/import', dependencies=[Depends(admin)])
def import_users(body: HistoryImportRequest, request: Request):
    return outcome(request,AdminDataService(request.app.state.engine).import_history(body))


@router.post('/api/control/v1/catalogs/import', dependencies=[Depends(admin)])
def import_catalog(body: CatalogImportRequest, request: Request):
    try:
        path = prepared_path(body.bundle_path)
        with Session(request.app.state.engine) as session,session.begin():
            bundle = import_catalog_file(session, path)
            session.add(db.OperatorAuditEvent(action='catalog_registered',target_id=bundle.dataset_snapshot_id,document={'source_hash':digest(path)}))
    except ImmutableCatalog:
        raise HTTPException(409,'ARTIFACT_IMMUTABLE')
    except (OSError,ValueError,KeyError,PsycopgError,SQLAlchemyError):
        raise HTTPException(422,'ARTIFACT_NOT_READY')
    return {'request_id':request.state.request_id,'catalog_snapshot_id':bundle.dataset_snapshot_id,
            'review_snapshot_id':bundle.review_snapshot_id,'history_snapshot_id':bundle.history_snapshot_id}


@router.get('/api/control/v1/users', dependencies=[Depends(admin)])
def list_users(request: Request, history_snapshot_id: str, environment_version_id: str | None = None,
               query: str = '', offset: int = Query(default=0,ge=0), limit: int = Query(default=50,ge=1,le=200)):
    with Session(request.app.state.engine) as session:
        selection=select(catalog.HistoricalUser).where(catalog.HistoricalUser.history_snapshot_id == history_snapshot_id)
        if query: selection=selection.where(catalog.HistoricalUser.user_id.startswith(query,autoescape=True))
        users = list(session.scalars(selection.order_by(catalog.HistoricalUser.user_id).offset(offset).limit(limit)))
        counts = dict(session.execute(select(catalog.HistoricalInteraction.user_id,func.count()).where(
            catalog.HistoricalInteraction.history_snapshot_id == history_snapshot_id,
            catalog.HistoricalInteraction.user_id.in_([u.user_id for u in users])).group_by(catalog.HistoricalInteraction.user_id)).all())
        environment = session.get(db.EnvironmentVersion,environment_version_id) if environment_version_id else None
        if environment_version_id and (environment is None or environment.history_snapshot_id != history_snapshot_id):
            raise HTTPException(422,'ARTIFACT_MISMATCH')
        values = []
        for u in users:
            eligibility = []
            if environment:
                for source in from_environment(environment.config).ranking_sources.values():
                    try:
                        request.app.state.ranking.validate_policy(PolicyValidationRequest(catalog_snapshot_id=environment.dataset_snapshot_id,
                            user=UserContext(user_id=u.user_id,history_snapshot_id=history_snapshot_id),
                            policy=source.policy))
                        eligibility.append(source.policy.family)
                    except RankingFailure:
                        pass
            values.append({'user_id':u.user_id,'history_snapshot_id':history_snapshot_id,
                'interaction_count':counts.get(u.user_id,0),'eligible_configured_policies':sorted(set(eligibility)) if environment else None})
        return {'request_id':request.state.request_id,'users':values}
