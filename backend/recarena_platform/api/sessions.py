"""HTTP sessions boundary."""
from fastapi import Depends, Header, Request
from recarena_contracts.http import SessionCreate, SessionEnd
from recarena_platform.sessions import SessionService
from recarena_platform.api.dependencies import outcome, session_api
from fastapi import APIRouter
router = APIRouter()


@router.post('/api/sessions', dependencies=[Depends(session_api)])
def issue_session(body: SessionCreate, request: Request,
                  idempotency_key: str | None = Header(default=None, alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, SessionService(request.app.state.engine, request.app.state.ranking).issue(
        body.model_dump(mode='json'), idempotency_key))


@router.post('/api/sessions/{session_id}/end', dependencies=[Depends(session_api)])
def end_session(session_id: str, body: SessionEnd, request: Request):
    return outcome(request, SessionService(request.app.state.engine).end(session_id, body.reason))
