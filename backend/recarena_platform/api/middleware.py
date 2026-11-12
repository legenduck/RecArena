"""HTTP middleware boundary."""
import json
import os
import re
from uuid import uuid4
from fastapi import Request
from recarena_platform.request_context import request_context
from recarena_platform.api.dependencies import COOKIE
from recarena_platform.api.errors import error_response


async def request_identity(request: Request, call_next):
    request.state.request_id = str(uuid4())
    original_path = request.scope['path']
    match = re.fullmatch(r'/s/([^/]+)(/(?:api/shop/.*|assets/.*))', original_path)
    request.state.url_credential = match[1] if match else None
    if match:
        request.scope['path'] = match[2]
        request.scope['raw_path'] = match[2].encode()
    access_path = 'url' if match else 'cookie_redirect' if request.cookies.get(COOKIE) else 'none'
    kind = request.headers.get('x-recarena-response-kind', 'data_api')
    context = request_context.set({'request_id':request.state.request_id, 'access_path':access_path,
        'user_agent':request.headers.get('user-agent'),
        'response_kind':'control' if request.url.path.startswith(('/api/control/','/api/sessions')) else kind if kind in {'html','data_api'} else 'data_api',
        'session_prefix':f'/s/{match[1]}' if match else ''})
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.url.path.startswith('/api/shop/'):
        origin = request.headers.get('origin')
        allowed_origins={os.environ.get('RECARENA_SHOP_URL','http://127.0.0.1:5173').rstrip('/'),
                         *json.loads(os.environ.get('RECARENA_SHOP_ORIGINS','[]'))}
        if origin and origin not in allowed_origins:
            response = error_response(request, 'INVALID_SESSION', 403)
            response.headers['X-Robots-Tag'] = 'noindex'
            request_context.reset(context)
            return response
    try:
        response = await call_next(request)
    finally:
        request_context.reset(context)
    if not request.url.path.startswith(('/api/shop/', '/assets/')):
        response.headers['X-Request-ID'] = request.state.request_id
    if response.status_code >= 400 or 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex'
    return response
