"""HTTP assets boundary."""
from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from recarena_platform.db import runtime as db
from recarena_platform.events import record_event
from recarena_platform.contexts import lock_login, current_scope
from recarena_platform.api.dependencies import credential
from recarena_platform.api.errors import error_response
from fastapi import APIRouter
router = APIRouter()


@router.get('/assets/{asset_id}')
def asset(asset_id: str, request: Request):
    with Session(request.app.state.engine) as session, session.begin():
        login, error = lock_login(session, credential(request))
        if error:
            raise HTTPException(error.status, error.error)
        scope = current_scope(session, login)
        if login.entry_id is not None and (scope is None or scope.state != 'RUNNING'):
            if scope:
                record_event(session, scope, 'ended_session_access', {'resource':'asset', 'state':scope.state})
            return error_response(request, 'RUN_TERMINAL', 410)
        if scope is None or scope.environment_version_id is None:
            raise HTTPException(403, 'CROSS_SESSION_ACCESS_DENIED')
        catalog_id = session.get(db.EnvironmentVersion, scope.environment_version_id).dataset_snapshot_id
    selected = request.app.state.assets.get((catalog_id, asset_id))
    reference = selected or request.app.state.assets.get((catalog_id, 'placeholder'))
    if reference is None:
        raise HTTPException(404, 'RESULT_NOT_FOUND')
    try:
        path, file_stat = reference.resolve_file()
    except (OSError, ValueError):
        return error_response(request, 'ASSET_NOT_READY', 503)
    headers = {'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Content-Type-Options': 'nosniff',
               'Vary': 'Cookie',
               'Cache-Control': 'private, max-age=86400, immutable' if selected else 'no-store'}
    # FileResponse derives cache validators from stat metadata and streams bytes.
    # Conditional requests never open/read the complete image.
    response = FileResponse(path, media_type=reference.media_type, headers=headers, stat_result=file_stat)
    etag = response.headers['etag']
    tags = [tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match', '').split(',')]
    if etag in tags or '*' in tags:
        return Response(status_code=304, headers={**headers, 'ETag': etag})
    return response
