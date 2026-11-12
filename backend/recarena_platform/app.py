"""Application composition and resource lifetime. HTTP handlers live in api/."""
from contextlib import AsyncExitStack, asynccontextmanager
import os

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from recarena_platform.db import engine_from_env
from recarena_platform.ranking_client import RankingClient
from recarena_platform.catalog.assets import load_asset_config
from recarena_platform.reporting.exports import ExportRecoveryWorker
from recarena_platform.api import assets, catalog, comparisons, environments, health, reports, runs, sessions, shop
from recarena_platform.api.errors import http_error, invalid_request
from recarena_platform.api.middleware import request_identity


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as resources:
        app.state.engine = engine_from_env()
        resources.callback(app.state.engine.dispose)
        app.state.ranking = RankingClient()
        resources.callback(app.state.ranking.close)
        app.state.assets = load_asset_config(os.environ.get('RECARENA_ASSET_CONFIG'))
        worker = ExportRecoveryWorker(app.state.engine) if os.environ.get('RECARENA_WORKER_ENABLED', 'true').lower() == 'true' else None
        app.state.export_worker = worker
        if worker:
            worker.start()
            resources.callback(worker.stop)
        yield


def create_app():
    app = FastAPI(title='RecArena Platform', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.middleware('http')(request_identity)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    for module in (health, environments, catalog, comparisons, reports, runs, sessions, shop, assets):
        app.include_router(module.router)
    return app


app = create_app()
