"""Session-owned cart operations share the existing context locks and purchase transaction."""
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.commerce import item_totals
from recarena_contracts.layout import from_environment
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.contexts import lock_context
from recarena_platform.request_context import image_urls
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.runs import guard_running
from recarena_platform.events import record_event
from recarena_platform.idempotency import action_retry, save_action_receipt
from recarena_platform.shopping.purchases import purchase_dto

from recarena_platform.shopping.purchases import purchasable_variant, purchase_item, confirm_purchase


class CartService:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def enabled(session, scope):
        env = session.get(db.EnvironmentVersion, scope.environment_version_id)
        return env and from_environment(env.config).layout.cart_enabled

    def response(self, session, scope, cart):
        items = []
        for line in cart.items if cart else []:
            variant, error = purchasable_variant(session, scope, line['product_id'], line['variant_id'])
            if error:
                return error
            product = session.get(catalog.Product, (variant.dataset_snapshot_id, line['product_id']))
            images = image_urls(variant.dataset_snapshot_id, remote=variant.document.get('image_urls', ()),
                local=variant.document.get('image_asset_ids', ())) or image_urls(variant.dataset_snapshot_id,
                remote=product.document.get('image_urls', ()), local=product.document.get('image_asset_ids', ()),
                placeholder=True)
            items.append({**purchase_item(session, variant, line['quantity'], line.get('origin_placement_id')),
                          'item_id': line['item_id'], 'image_url': images[0],
                          'is_available': variant.is_available, 'is_purchasable': variant.is_purchasable})
        identifier = str(uuid4())
        session.add(db.ShoppingView(id=identifier, context_id=scope.id, kind='cart',
            document={'version': cart.version if cart else 0,
                      'items': {item['item_id']: {'product_id': item['product_id'], 'origin': item['origin_placement_id']} for item in items}}))
        return Outcome({'viewId': identifier, 'items': items, **item_totals(items)})

    def inspect(self, credential, context_id):
        with Session(self.engine) as session, session.begin():
            scope, error = lock_context(session, credential, context_id)
            if error: return error
            if error := guard_running(session, scope): return error
            if not self.enabled(session, scope): return rejected('CART_DISABLED', 404)
            result = self.response(session, scope, session.get(db.Cart, scope.id))
            if not result.error:
                record_event(session, scope, 'cart_served', {'items': [
                    {key: item[key] for key in ('product_id','variant_id','quantity')}
                    for item in result.value['items']]})
            return result

    def change(self, credential, context_id, action, payload, key, *, expected_version=None):
        fingerprint = canonical_hash({'action': action, 'payload': payload, 'version': expected_version})
        with Session(self.engine) as session, session.begin():
            scope, error = lock_context(session, credential, context_id)
            if error: return error
            if retry := action_retry(session, scope.id, 'cart', key, fingerprint): return retry
            if error := guard_running(session, scope): return error
            if not self.enabled(session, scope): return rejected('CART_DISABLED', 404)
            cart = session.get(db.Cart, scope.id)
            if cart is None:
                cart = db.Cart(context_id=scope.id, version=0, items=[])
                session.add(cart)
            if expected_version is not None and expected_version != cart.version:
                return rejected('CART_CHANGED')
            lines = [dict(line) for line in cart.items]
            if action == 'add':
                variant, error = purchasable_variant(session, scope, payload['product_id'], payload['variant_id'])
                if error: return error
                origin = payload.get('origin_placement_id')
                if origin:
                    placement = session.get(db.Placement, origin)
                    if placement is None or placement.context_id != scope.id or placement.product_id != payload['product_id']:
                        return rejected('CROSS_SESSION_ACCESS_DENIED', 403)
                line = next((line for line in lines if line['variant_id'] == payload['variant_id'] and line['product_id'] == payload['product_id']), None)
                if line is None:
                    line = {**payload, 'item_id': str(uuid4()), 'quantity': 0}
                    lines.append(line)
                quantity = line['quantity'] + payload['quantity']
                event = 'cart_item_added'
            else:
                line = next((line for line in lines if line['item_id'] == payload['item_id']), None)
                if line is None: return rejected('CART_ITEM_NOT_FOUND', 404)
                quantity = payload.get('quantity', line['quantity'])
                event = 'cart_item_removed' if action == 'remove' else 'cart_item_updated'
            if quantity < 1 or quantity > scope.limits['max_quantity']:
                return rejected('INVALID_QUANTITY', 422)
            old_quantity = line['quantity']
            if action == 'update' and quantity == old_quantity:
                return save_action_receipt(session, scope.id, 'cart', key, fingerprint, self.response(session, scope, cart))
            if action == 'remove': lines.remove(line)
            else: line['quantity'] = quantity
            cart.items, cart.version = lines, cart.version + 1
            record_event(session, scope, event, {**payload, 'item_id': line['item_id'],
                'product_id': line['product_id'], 'variant_id': line['variant_id'],
                'previous_quantity': old_quantity, 'quantity': 0 if action == 'remove' else quantity})
            result = self.response(session, scope, cart)
            if result.error:
                session.rollback()
                return result
            return save_action_receipt(session, scope.id, 'cart', key, fingerprint, result)

    def checkout(self, credential, context_id, version, key):
        fingerprint = canonical_hash({'context_id': context_id, 'cart_version': version})
        with Session(self.engine) as session, session.begin():
            scope, error = lock_context(session, credential, context_id)
            if error: return error
            if retry := action_retry(session, scope.id, 'purchase', key, fingerprint): return retry
            existing = session.scalar(select(db.Purchase).where(db.Purchase.context_id == scope.id, db.Purchase.idempotency_key == key))
            if existing:
                return Outcome(purchase_dto(existing)) if existing.request_hash == fingerprint else rejected('IDEMPOTENCY_CONFLICT')
            record_event(session, scope, 'purchase_requested', {'purchase_source': 'cart', 'logical_request_id': key})
            error = guard_running(session, scope)
            cart = session.get(db.Cart, scope.id)
            if not error and not self.enabled(session, scope): error = rejected('CART_DISABLED', 404)
            if not error and not scope.user_id: error = rejected('USER_REQUIRED', 401)
            if not error and (cart is None or not cart.items): error = rejected('CART_EMPTY')
            if not error and cart.version != version: error = rejected('CART_CHANGED')
            items = []
            if not error:
                for line in cart.items:
                    variant, error = purchasable_variant(session, scope, line['product_id'], line['variant_id'])
                    if error: break
                    if not 1 <= line['quantity'] <= scope.limits['max_quantity']:
                        error = rejected('INVALID_QUANTITY', 422); break
                    items.append(purchase_item(session, variant, line['quantity'], line.get('origin_placement_id')))
            if error:
                record_event(session, scope, 'purchase_rejected', {'code': error.error, 'purchase_source': 'cart'})
                return save_action_receipt(session, scope.id, 'purchase', key, fingerprint, error)
            result = confirm_purchase(session, scope, items, variant.dataset_snapshot_id, key, fingerprint, 'cart')
            cart.items, cart.version = [], cart.version + 1
            return result
