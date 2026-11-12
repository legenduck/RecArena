"""HTTP errors boundary."""
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from recarena_contracts.artifacts import canonical_hash
from recarena_platform.api.dependencies import browser_shop, credential


def error_response(request, code, status):
    public = request.url.path.startswith(('/api/shop/', '/assets/'))
    if public:
        code = {'RUN_TERMINAL':'SHOPPING_ENDED', 'STALE_CONTEXT':'VIEW_EXPIRED',
                'CROSS_RUN_ACCESS_DENIED':'VIEW_ACCESS_DENIED', 'CROSS_SESSION_ACCESS_DENIED':'VIEW_ACCESS_DENIED',
                'POLICY_EXECUTION_FAILED':'SHOP_SERVICE_UNAVAILABLE', 'SITE_NOT_CONFIGURED':'SHOP_SERVICE_UNAVAILABLE'}.get(code, code)
    return JSONResponse(status_code=status, content={'error': {'code': code,
        'message': code.replace('_', ' ').capitalize() + '.',
        **({} if public else {'request_id': request.state.request_id}),
        'retryable': status >= 500}})


async def http_error(request, error):
    return error_response(request, str(error.detail), error.status_code)


async def invalid_request(request, error):
    # Never reflect validation input containing claim tokens, cookies or private data.
    code = 'INVALID_QUANTITY' if any('quantity' in e['loc'] for e in error.errors()) else 'INVALID_INPUT'
    if request.method=='POST' and request.url.path in {'/api/shop/v1/purchases','/api/shop/v1/cart/checkout'}:
        try:
            payload_hash=canonical_hash(error.body)
        except (ValueError,TypeError):
            payload_hash=None
        recorded=await run_in_threadpool(browser_shop(request).rejected_purchase_input,
            credential(request),error.body,code,request.headers.get('Idempotency-Key'),payload_hash)
        if recorded and recorded.error:
            return error_response(request,recorded.error,recorded.status)
    return error_response(request, code, 422)
