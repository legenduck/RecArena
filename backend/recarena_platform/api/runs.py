"""HTTP runs boundary."""
import os
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from recarena_contracts.http import PreparedRunStart, RunCreate
from recarena_platform.db import runtime as db
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.environments import ensure_ready
from recarena_platform.reporting.queries import filtered_runs
from recarena_platform.api.dependencies import admin, outcome
from fastapi import APIRouter
router = APIRouter()
from recarena_platform.runs import RunService


@router.post('/api/control/v1/runs', dependencies=[Depends(admin)])
def create_run(body: RunCreate, request: Request):
    with Session(request.app.state.engine) as session:
        environment = session.get(db.EnvironmentVersion, body.environment_version_id)
        if environment is None or environment.state != 'PUBLISHED':
            raise HTTPException(422, 'ARTIFACT_NOT_READY')
        try:
            ensure_ready(session, request.app.state.ranking, environment, body.user_id, strict_user=body.run_kind != 'preview')
        except (KeyError, ValueError, RankingFailure):
            raise HTTPException(422, 'ARTIFACT_NOT_READY')
    result = outcome(request, RunService(request.app.state.engine).create_run(body.environment_version_id, body.user_id,
        task_id=body.task_version_id, limits=body.limits.model_dump(), run_kind=body.run_kind))
    result['shop_url'] = os.environ.get('RECARENA_SHOP_URL', 'http://127.0.0.1:5173').rstrip('/') + '/'
    result['limits'] = body.limits.model_dump()
    result['connection_profile'] = 'external_browser'
    return result


@router.get('/api/control/v1/runs', dependencies=[Depends(admin)])
def list_runs(request: Request, experiment_id: str | None = None, offset: int = Query(default=0,ge=0), limit: int = Query(default=100,ge=1,le=1000),
              run_id: str | None = None, user_id: str | None = None, requested_policy: str | None = None,
              applied_policy: str | None = None, agent_label: str | None = None,
              external_task_id: str | None = None, client_run_id: str | None = None,
              state: str | None = None, run_kind: str | None = None, recording_method: str | None = None):
    with Session(request.app.state.engine) as session:
        query = filtered_runs({'run_id':run_id,'user_id':user_id,'requested_policy':requested_policy,'applied_policy':applied_policy,
            'agent_label':agent_label,'external_task_id':external_task_id,'client_run_id':client_run_id,
            'state':state,'run_kind':run_kind,'recording_method':recording_method})
        if experiment_id is not None:
            query = query.where(db.Run.experiment_id == experiment_id)
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        runs = list(session.scalars(query.order_by(db.Run.created_at.desc(),db.Run.id).offset(offset).limit(limit)))
        purchases={p.run_id:p.id for p in session.scalars(select(db.Purchase).where(db.Purchase.run_id.in_([r.id for r in runs])))}
        fields = ('id','state','run_kind','user_id','task_version_id','environment_version_id',
                  'experiment_id','condition_id','pair_id','repetition','seed','started_at','ended_at','created_at',
                  'shop_session_id','requested_policy','agent_label','external_task_id','client_run_id',
                  'entry_encoding','entry_snapshot','first_interaction_at','end_reason','recording_method')
        return {'request_id':request.state.request_id,'total':total,'offset':offset,'limit':limit,
            'runs':[{**{k:getattr(r,k) for k in fields},'purchase_id':purchases.get(r.id)} for r in runs]}


@router.get('/api/control/v1/runs/{run_id}', dependencies=[Depends(admin)])
def inspect_run(run_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        run = session.get(db.Run, run_id)
        if run is None:
            raise HTTPException(404, 'RESULT_NOT_FOUND')
        return {key: getattr(run, key) for key in ('id', 'state', 'environment_version_id',
            'user_id', 'history_snapshot_id', 'task_version_id', 'limits', 'connection', 'started_at', 'ended_at', 'run_kind',
            'experiment_id','condition_id','pair_id','repetition','seed','created_at','shop_session_id','requested_policy',
            'agent_label','external_task_id','client_run_id','entry_encoding','entry_config','entry_snapshot',
            'configuration_digest','first_interaction_at','end_reason','recording_method')} | {'request_id': request.state.request_id}


@router.post('/api/control/v1/runs/{run_id}/cancel', dependencies=[Depends(admin)])
def cancel(run_id: str, request: Request):
    return outcome(request, RunService(request.app.state.engine).cancel(run_id))


@router.post('/api/control/v1/runs/{run_id}/start', dependencies=[Depends(admin)])
def start_prepared_run(run_id: str, body: PreparedRunStart, request: Request):
    with Session(request.app.state.engine) as session:
        run = session.get(db.Run,run_id)
        if run is None: raise HTTPException(404,'RESULT_NOT_FOUND')
        environment = session.get(db.EnvironmentVersion,run.environment_version_id)
        try: ensure_ready(session,request.app.state.ranking,environment,run.user_id,strict_user=run.run_kind!='preview')
        except (KeyError,ValueError,RankingFailure): raise HTTPException(422,'POLICY_NOT_READY')
    return outcome(request,RunService(request.app.state.engine).start_prepared(run_id,body.shop_session_id))
