"""Browser-only projection and persistent view references over existing shop services."""
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from recarena_contracts import browser as web
from recarena_contracts.events import ClientEvent, ClientEventsBatch, RECORDING_METHOD
from recarena_contracts.models import SearchRequest, SelectionRequest, PurchaseRequest
from recarena_platform.db import runtime as db
from recarena_platform.contexts import lock_context
from recarena_platform.shopping.observations import ClientEventService
from recarena_platform.shopping.service import ShopService
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.shopping.purchases import PurchaseService
from recarena_platform.shopping.cart import CartService


def pick(model, value, **extra):
    """Select only declared transport fields, including nested schema validation."""
    return model.model_validate({**{k: value[k] for k in model.model_fields if k in value}, **extra}).model_dump(mode='json')


class BrowserShop:
    def __init__(self, engine, ranking, request_id):
        self.engine, self.request_id = engine, request_id
        self.shop = ShopService(engine, ranking, request_id)
        self.purchases = PurchaseService(engine)
        self.carts = CartService(engine)

    @staticmethod
    def receipt(value):
        return pick(web.BrowserReceipt, value,
            items=[pick(web.BrowserReceiptItem, item) for item in value['items']])

    @staticmethod
    def cart_response(result):
        if result.error: return result
        return Outcome(pick(web.BrowserCart, result.value,
            items=[pick(web.BrowserCartItem, item) for item in result.value['items']]))

    def save_view(self, session, context_id, kind, document):
        identifier = str(uuid4())
        session.add(db.ShoppingView(id=identifier, context_id=context_id, kind=kind, document=document))
        return identifier

    def _resolve(self, session, credential, view_id, kinds=None):
        view = session.get(db.ShoppingView, str(view_id))
        if view is None:
            return None, None, rejected('VIEW_NOT_FOUND', 404)
        scope, error = lock_context(session, credential, view.context_id, telemetry=True)
        if error:
            return None, None, error
        if kinds and view.kind not in kinds:
            return None, None, rejected('INVALID_VIEW', 422)
        return view, scope, None

    def resolve(self, credential, view_id, kinds=None):
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            view, _, error = self._resolve(session, credential, view_id, kinds)
            return view, error

    def session_info(self, credential):
        return self.shop.session_info(credential, present=self.session_response)

    def session_response(self, session, result):
        value = result.value
        status = {'RUNNING': 'active', 'PURCHASED': 'purchased', 'ABANDONED': 'abandoned'}.get(value['state'], 'ended')
        view_id = self.save_view(session, value['context_id'], 'home' if status == 'active' else 'terminal', {})
        receipt = self.receipt(value['purchase']) if value['purchase'] else None
        return Outcome(web.BrowserSession(viewId=view_id, status=status, max_quantity=value['max_quantity'],
            show_abandon=value['show_abandon'], show_cart=value['show_cart'],
            cart_quantity=value['cart_quantity'], purchase=receipt).model_dump(mode='json'))

    def results_response(self, session, result, presentation):
        value = result.value
        aliases = {f'list-{i}': block.id for i, block in enumerate(presentation.layout.blocks, 1)}
        reverse = {v: k for k, v in aliases.items()}
        blocks = value.get('blocks', [value['block']] if 'block' in value else [])
        bindings = {}
        for block in blocks:
            alias = reverse[block['block_id']]
            bindings[alias] = {'block_id': block['block_id'], 'section_page': block['section_page'],
                'items': {f'{alias}:{i}': {'product_id': card['product_id'], 'placement_id': card['placement_id']}
                          for i, card in enumerate(block['items'], 1)}}
        view_id = self.save_view(session, value['context_id'], 'results', {
            'snapshot_id': value['result_snapshot_id'], 'main_page': value['main_page'],
            'aliases': aliases, 'blocks': bindings})
        public_blocks = []
        for block in blocks:
            alias = reverse[block['block_id']]
            cards = [pick(web.BrowserCard, card, item_key=f'{alias}:{i}') for i, card in enumerate(block['items'], 1)]
            public_blocks.append(pick(web.BrowserBlock, block, viewId=view_id, block_id=alias,
                title='Search results' if alias == 'list-1' else 'More items', items=cards))
        if 'block' in value:
            return Outcome(pick(web.BrowserBlockResponse, value, viewId=view_id, block=public_blocks[0]))
        return Outcome(pick(web.BrowserResults, value, viewId=view_id, blocks=public_blocks))

    def search(self, credential, body):
        def prepare(session):
            view, scope, error = self._resolve(session, credential, body.viewId)
            if error:
                return None, None, error
            try:
                request = SearchRequest(context_id=view.context_id, query=body.query, client_request_id=body.requestKey)
            except ValidationError:
                return None, None, rejected('INVALID_INPUT', 422)
            return scope, request, None
        return self.shop.search(credential, None, prepare=prepare, present=self.results_response)

    def results(self, credential, view_id, page, sections, filters, only_block=None):
        with Session(self.engine) as session, session.begin():
            view, scope, error = self._resolve(session, credential, view_id, {'results'})
            if error:
                return error
            aliases = view.document['aliases']
            if not set(sections).issubset(aliases) or (only_block is not None and only_block not in aliases):
                return rejected('INVALID_INPUT', 422)
            return self.shop.results(credential, view.document['snapshot_id'], page,
                {aliases[k]: v for k, v in sections.items()}, aliases.get(only_block), filters,
                session=session, scope=scope, present=self.results_response)

    @staticmethod
    def item(view, item_key, product_id=None):
        for block in view.document.get('blocks', {}).values():
            item = block['items'].get(item_key)
            if item and (product_id is None or item['product_id'] == product_id):
                return item
        return None

    def origin(self, view, product_id, item_key):
        if view.kind == 'cart' and item_key is not None:
            item = view.document['items'].get(item_key)
            return (item.get('origin'), None) if item and item['product_id'] == product_id else (None, rejected('INVALID_ITEM_REFERENCE', 422))
        if item_key is not None:
            item = self.item(view, item_key, product_id)
            return (item['placement_id'], None) if item else (None, rejected('INVALID_ITEM_REFERENCE', 422))
        if view.kind == 'detail' and view.document['product_id'] == product_id:
            return view.document.get('origin'), None
        return None, None

    def detail(self, credential, product_id, view_id, item_key=None):
        with Session(self.engine) as session, session.begin():
            view, scope, error = self._resolve(session, credential, view_id)
            if error:
                return error
            origin, error = self.origin(view, product_id, item_key)
            if error:
                return error
            result = self.shop.detail(credential, product_id, origin, view.context_id, session=session, scope=scope)
            if result.error:
                return result
            identifier = self.save_view(session, view.context_id, 'detail', {'product_id': product_id, 'origin': origin})
            return Outcome(pick(web.BrowserProduct, result.value, viewId=identifier))

    def reviews(self, credential, product_id, view_id, offset, limit):
        with Session(self.engine) as session, session.begin():
            view, scope, error = self._resolve(session, credential, view_id, {'detail', 'reviews'})
            if error:
                return error
            if view.document['product_id'] != product_id:
                return rejected('INVALID_ITEM_REFERENCE', 422)
            result = self.shop.reviews(credential, product_id, offset, limit, view.context_id,
                session=session, scope=scope)
            if result.error:
                return result
            identifier = self.save_view(session, view.context_id, 'reviews', {'product_id': product_id, 'offset': offset,
                'review_ids': [r['review_id'] for r in result.value['reviews']]})
            return Outcome(pick(web.BrowserReviews, result.value, viewId=identifier))

    def selection(self, credential, product_id, body):
        view, error = self.resolve(credential, body.viewId, {'detail'})
        if error:
            return error
        if view.document['product_id'] != product_id:
            return rejected('INVALID_ITEM_REFERENCE', 422)
        result = self.purchases.select_variant(credential, product_id, SelectionRequest(context_id=view.context_id,
            client_request_id=body.requestKey, variant_id=body.variant_id, quantity=body.quantity))
        if result.error:
            return result
        return Outcome({'variant_id': result.value['variant_id'], 'quantity': result.value['quantity'],
            'unit_price_minor': result.value['unit_price_minor'], 'currency': result.value['currency']})

    def purchase(self, credential, body, key):
        view, error = self.resolve(credential, body.viewId, {'detail', 'results'})
        if error:
            return error
        if (view.kind == 'detail' and view.document['product_id'] != body.product_id) or (view.kind == 'results' and body.item_key is None):
            return rejected('INVALID_ITEM_REFERENCE', 422)
        origin, error = self.origin(view, body.product_id, body.item_key)
        if error:
            return error
        result = self.purchases.purchase(credential, PurchaseRequest(context_id=view.context_id, product_id=body.product_id,
            variant_id=body.variant_id, quantity=body.quantity, origin_placement_id=origin), key)
        return result if result.error else Outcome(self.receipt(result.value))

    def cart(self, credential, view_id):
        view, error = self.resolve(credential, view_id)
        if error: return error
        return self.cart_response(self.carts.inspect(credential, view.context_id))

    def cart_add(self, credential, body, key):
        view, error = self.resolve(credential, body.viewId, {'detail', 'results'})
        if error: return error
        if (view.kind == 'detail' and view.document['product_id'] != body.product_id) or (view.kind == 'results' and body.item_key is None):
            return rejected('INVALID_ITEM_REFERENCE', 422)
        origin, error = self.origin(view, body.product_id, body.item_key)
        if error: return error
        payload = {'product_id': body.product_id, 'variant_id': body.variant_id,
                   'quantity': body.quantity, 'origin_placement_id': origin}
        return self.cart_response(self.carts.change(credential, view.context_id, 'add', payload, key))

    def cart_change(self, credential, item_id, body, key, *, remove=False):
        view, error = self.resolve(credential, body.viewId, {'cart'})
        if error: return error
        if item_id not in view.document['items']: return rejected('CART_ITEM_NOT_FOUND', 404)
        payload = {'item_id': item_id, **({} if remove else {'quantity': body.quantity})}
        return self.cart_response(self.carts.change(credential, view.context_id, 'remove' if remove else 'update',
            payload, key, expected_version=view.document['version']))

    def cart_checkout(self, credential, body, key):
        view, error = self.resolve(credential, body.viewId, {'cart'})
        if error: return error
        result = self.carts.checkout(credential, view.context_id, view.document['version'], key)
        return result if result.error else Outcome(self.receipt(result.value))

    def rejected_purchase_input(self, credential, body, code, key, payload_hash):
        if not isinstance(body, dict) or not isinstance(body.get('viewId'), str):
            return None
        view, error = self.resolve(credential, body['viewId'], {'detail', 'results', 'cart'})
        if error:
            return error
        return self.purchases.rejected_purchase_input(credential, code, self.request_id, view.context_id, key, payload_hash)

    def abandon(self, credential, body):
        view, error = self.resolve(credential, body.viewId)
        if error:
            return error
        result = self.purchases.abandon(credential, view.context_id)
        return result if result.error else Outcome({'status': 'abandoned'})

    @staticmethod
    def event_payload(view, event):
        """Translate only facts reported by the browser; never synthesize observations."""
        p, doc, kind = event.payload, view.document, event.event_type
        if kind == 'page_viewed':
            if p or view.kind == 'reviews':
                raise ValueError('Invalid page display')
            return {'page_type': view.kind,
                **({'result_snapshot_id': doc['snapshot_id']} if view.kind == 'results' else {}),
                **({'product_id': doc['product_id']} if view.kind == 'detail' else {})}
        if kind == 'scroll_sampled':
            return p  # Existing ScrollPayload performs the strict validation below.
        if kind in {'item_list_rendered', 'product_clicked', 'section_page_changed'}:
            expected = {'block_id', 'list_presentation_id', 'item_keys'} if kind == 'item_list_rendered' else (
                {'block_id', 'list_presentation_id', 'item_key'} if kind == 'product_clicked' else {'block_id'})
            if set(p) != expected or view.kind != 'results':
                raise ValueError('Invalid list event')
            block = doc['blocks'][p['block_id']]
            common = {'result_snapshot_id': doc['snapshot_id'], 'block_id': block['block_id']}
            if kind == 'section_page_changed':
                return {**common, 'main_page': doc['main_page'], 'section_page': block['section_page']}
            common['list_presentation_id'] = p['list_presentation_id']
            if kind == 'product_clicked':
                return {**common, 'placement_id': block['items'][p['item_key']]['placement_id']}
            # JSONB object ordering is not insertion ordering; use explicit positions.
            ordered = sorted(block['items'], key=lambda k: int(k.rsplit(':', 1)[1]))
            if p['item_keys'] != ordered:
                raise ValueError('Displayed items differ from the issued list')
            return {**common, 'main_page': doc['main_page'], 'section_page': block['section_page'],
                'items': [block['items'][key] for key in p['item_keys']]}
        if kind == 'result_page_changed':
            if p or view.kind != 'results':
                raise ValueError('Invalid page event')
            return {'result_snapshot_id': doc['snapshot_id'], 'main_page': doc['main_page']}
        if kind == 'reviews_rendered':
            if view.kind != 'reviews' or set(p) != {'review_ids'} or p['review_ids'] != doc['review_ids']:
                raise ValueError('Invalid review display')
            return {k: doc[k] for k in ('product_id', 'offset', 'review_ids')}
        if kind in {'review_section_entered', 'review_expanded'}:
            if p or view.kind != 'detail':
                raise ValueError('Invalid review action')
            return {'product_id': doc['product_id']}
        raise ValueError('Unsupported browser event')

    def events(self, credential, body):
        canonical = []
        views = {}
        try:
            for event in body.events:
                key = str(event.viewId)
                if key not in views:
                    view, error = self.resolve(credential, key)
                    if error:
                        return error
                    views[key] = view
                view = views[key]
                canonical.append(ClientEvent(context_id=view.context_id, event_id=event.event_id,
                    event_type=event.event_type, occurred_at=event.occurred_at,
                    page_instance_id=event.documentId or event.viewId,
                    view_id=event.viewId if event.documentId else None,
                    client_sequence=event.client_sequence, recording_method=RECORDING_METHOD,
                    payload=self.event_payload(view, event)))
        except (KeyError, TypeError, ValueError, ValidationError):
            return rejected('INVALID_EVENT', 422)
        result = ClientEventService(self.engine, self.request_id).batch(credential, ClientEventsBatch(events=canonical))
        if result.error:
            return result
        return Outcome({key: result.value[key] for key in ('accepted_event_ids', 'duplicate_event_ids')})
