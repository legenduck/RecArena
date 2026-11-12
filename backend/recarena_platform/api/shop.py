"""HTTP shop boundary."""
from fastapi import Header, HTTPException, Query, Request
from pydantic import TypeAdapter, StrictInt, ValidationError
from recarena_contracts.events import ClientEventsBatch
from recarena_platform.shopping.observations import ClientEventService
from recarena_contracts import browser as web
from recarena_platform.api.dependencies import browser_shop, credential, outcome
from fastapi import APIRouter
router = APIRouter()


@router.get('/api/shop/v1/session', response_model=web.BrowserSession)
def session_info(request: Request):
    return outcome(request, browser_shop(request).session_info(credential(request)))


@router.post('/api/shop/v1/search', response_model=web.BrowserResults)
def search(body: web.BrowserSearch, request: Request):
    return outcome(request, browser_shop(request).search(credential(request), body))


@router.get('/api/shop/v1/results/{view_id}', response_model=web.BrowserResults)
def results(view_id: str, request: Request, page: int = Query(default=1, ge=1), section_pages: str = '{}', filters: str = '{}'):
    from recarena_contracts.http import ResultFilters
    try:
        sections = TypeAdapter(dict[str, StrictInt]).validate_json(section_pages)
        selection = ResultFilters.model_validate_json(filters)
    except ValidationError:
        raise HTTPException(422, 'INVALID_INPUT')
    return outcome(request, browser_shop(request).results(credential(request), view_id, page, sections, selection))


@router.get('/api/shop/v1/results/{view_id}/blocks/{block_id}', response_model=web.BrowserBlockResponse)
def result_block(view_id: str, block_id: str, request: Request,
                 main_page: int = Query(default=1, ge=1), section_page: int = Query(default=1, ge=1), filters: str = '{}'):
    from recarena_contracts.http import ResultFilters
    try:
        selection = ResultFilters.model_validate_json(filters)
    except ValidationError:
        raise HTTPException(422, 'INVALID_INPUT')
    return outcome(request, browser_shop(request).results(credential(request), view_id, main_page,
        {block_id:section_page}, selection, block_id))


@router.get('/api/shop/v1/products/{product_id}', response_model=web.BrowserProduct)
def detail(product_id: str, request: Request, viewId: str, item: str | None = None):
    return outcome(request, browser_shop(request).detail(credential(request), product_id, viewId, item))


@router.get('/api/shop/v1/products/{product_id}/reviews', response_model=web.BrowserReviews)
def reviews(product_id: str, request: Request, offset: int = Query(default=0, ge=0),
            viewId: str = Query(), limit: int = Query(default=5, ge=1, le=50)):
    return outcome(request, browser_shop(request).reviews(credential(request), product_id, viewId, offset, limit))


@router.put('/api/shop/v1/products/{product_id}/selection')
def selection(product_id: str, body: web.BrowserSelection, request: Request):
    return outcome(request, browser_shop(request).selection(credential(request), product_id, body))


@router.post('/api/shop/v1/purchases', response_model=web.BrowserReceipt)
def purchase(body: web.BrowserPurchase, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, browser_shop(request).purchase(credential(request), body, idempotency_key))


@router.get('/api/shop/v1/cart', response_model=web.BrowserCart)
def cart(request: Request, viewId: str):
    return outcome(request, browser_shop(request).cart(credential(request), viewId))


@router.post('/api/shop/v1/cart/items', response_model=web.BrowserCart)
def cart_add(body: web.BrowserPurchase, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, browser_shop(request).cart_add(credential(request), body, idempotency_key))


@router.put('/api/shop/v1/cart/items/{item_id}', response_model=web.BrowserCart)
def cart_update(item_id: str, body: web.BrowserCartQuantity, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, browser_shop(request).cart_change(credential(request), item_id, body, idempotency_key))


@router.delete('/api/shop/v1/cart/items/{item_id}', response_model=web.BrowserCart)
def cart_remove(item_id: str, body: web.ViewRequest, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, browser_shop(request).cart_change(credential(request), item_id, body, idempotency_key, remove=True))


@router.post('/api/shop/v1/cart/checkout', response_model=web.BrowserReceipt)
def cart_checkout(body: web.ViewRequest, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    return outcome(request, browser_shop(request).cart_checkout(credential(request), body, idempotency_key))


@router.post('/api/shop/v1/abandon')
def abandon(body: web.ViewRequest, request: Request):
    return outcome(request, browser_shop(request).abandon(credential(request), body))


@router.post('/api/shop/v1/events/batch')
def client_event_batch(body: web.BrowserEvents | ClientEventsBatch, request: Request):
    # Browser observations and canonical batches share the same event validation.
    # Internal identifiers are never returned in the public acknowledgement.
    if isinstance(body, ClientEventsBatch):
        result = ClientEventService(request.app.state.engine, request.state.request_id).batch(credential(request), body)
        if result.error:
            raise HTTPException(result.status, result.error)
        return {key: result.value[key] for key in ('accepted_event_ids', 'duplicate_event_ids')}
    return outcome(request,browser_shop(request).events(credential(request),body))
