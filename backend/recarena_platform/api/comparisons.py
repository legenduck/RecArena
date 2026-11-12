"""HTTP comparisons boundary."""
import os
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_platform.db import runtime as db
from recarena_contracts.admin import ExperimentCreate
from recarena_platform.reporting.comparisons import ExperimentService, describe as describe_experiment
from recarena_platform.api.dependencies import admin, outcome
from fastapi import APIRouter
router = APIRouter()


@router.post('/api/control/v1/experiments', dependencies=[Depends(admin)])
def create_experiment(body: ExperimentCreate, request: Request):
    return outcome(request,ExperimentService(request.app.state.engine,request.app.state.ranking).create(body))


@router.get('/api/control/v1/experiments', dependencies=[Depends(admin)])
def list_experiments(request: Request):
    with Session(request.app.state.engine) as session:
        return {'request_id':request.state.request_id,'experiments':[describe_experiment(session,e)
            for e in session.scalars(select(db.Experiment).order_by(db.Experiment.created_at))]}


@router.get('/api/control/v1/experiments/{experiment_id}', dependencies=[Depends(admin)])
def inspect_experiment(experiment_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        value = session.get(db.Experiment,experiment_id)
        if value is None:
            raise HTTPException(404,'RESULT_NOT_FOUND')
        return {'request_id':request.state.request_id,**describe_experiment(session,value)}


@router.post('/api/control/v1/experiments/{experiment_id}/runs', dependencies=[Depends(admin)])
def generate_runs(experiment_id: str, request: Request):
    result = outcome(request,ExperimentService(request.app.state.engine,request.app.state.ranking).generate(experiment_id))
    for run in result['runs']:
        run['shop_url'] = os.environ.get('RECARENA_SHOP_URL','http://127.0.0.1:5173').rstrip('/')+'/'
        run['connection_profile'] = 'external_browser'
    return result
