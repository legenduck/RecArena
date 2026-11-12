"""HTTP dependencies boundary."""
import os
import secrets
from fastapi import Header, HTTPException
from recarena_platform.shopping.views import BrowserShop
COOKIE = os.environ.get('RECARENA_SESSION_COOKIE', 'recarena_session')

def admin(authorization: str | None = Header(default=None)):
    token = os.environ.get('RECARENA_ADMIN_TOKEN', '')
    if not token:
        raise HTTPException(503, 'ARTIFACT_NOT_READY')
    if not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, 'INVALID_SESSION')


def session_api(authorization: str | None = Header(default=None)):
    token = os.environ.get('RECARENA_SESSION_API_KEY', '')
    if not token:
        raise HTTPException(503, 'SESSION_API_KEY_NOT_CONFIGURED')
    if not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, 'INVALID_SESSION_API_KEY')


def credential(request):
    # A URL credential wins even when invalid; never fall back to another tab's cookie.
    return request.state.url_credential if request.state.url_credential is not None else request.cookies.get(COOKIE)


def outcome(request, result):
    if result.error:
        raise HTTPException(result.status, result.error)
    if request.url.path.startswith('/api/shop/'):
        return result.value
    value = {**result.value, 'request_id': request.state.request_id}
    if isinstance(value.get('purchase'), dict):
        value['purchase'] = {**value['purchase'], 'request_id': request.state.request_id}
    return value


def browser_shop(request):
    return BrowserShop(request.app.state.engine, request.app.state.ranking, request.state.request_id)
