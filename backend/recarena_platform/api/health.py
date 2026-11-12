"""HTTP health boundary."""
from fastapi import Depends, Request, Response
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from recarena_platform.db import SCHEMA_REVISION
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.api.dependencies import admin
from fastapi import APIRouter
router = APIRouter()


@router.get('/health/storage')
def storage(response: Response, request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            revision = connection.scalar(text('SELECT version_num FROM alembic_version'))
        ready = revision == SCHEMA_REVISION
    except Exception:
        revision, ready = None, False
    if not ready:
        response.status_code = 503
    return {'ready': ready, 'migration_revision': revision}


@router.get('/health/ready')
def readiness(response: Response, request: Request):
    result = storage(response, request)
    try:
        ready = bool(request.app.state.ranking.status()['ready'])
    except RankingFailure:
        ready = False
    if not result['ready'] or not ready:
        response.status_code = 503
    return {'ready': result['ready'] and ready, 'storage': result['ready'], 'ranking': ready}


@router.get('/api/control/v1/openapi.json', dependencies=[Depends(admin)])
def control_openapi(request: Request):
    return request.app.openapi()


@router.get('/api/shop/v1/openapi.json')
def shop_openapi(request: Request):
    return get_openapi(title='RecArena Shop', version='1.0',
        routes=[r for r in request.app.routes if r.path.startswith('/api/shop/')])
