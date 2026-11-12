"""Selections and confirmed transactions shared by cart and direct purchase."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import PurchaseRequest, SelectionRequest
from recarena_contracts.commerce import PurchaseItem, item_totals
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.contexts import lock_context
from recarena_platform.events import db_now, record_event
from recarena_platform.runs import finish, guard_running
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.idempotency import action_retry, save_action_receipt

def purchase_dto(purchase):
    result = {key: getattr(purchase, key) for key in (
        'id', 'run_id', 'context_id', 'product_id', 'variant_id', 'selected_options', 'quantity',
        'unit_price_minor', 'total_price_minor', 'currency', 'origin_placement_id', 'purchased_at')}
    items = purchase.items or [{key: result[key] for key in ('product_id','variant_id','selected_options','quantity','unit_price_minor','total_price_minor','currency','origin_placement_id')}]
    items = [{**item, 'title': item.get('title') or item['product_id']} for item in items]
    return {**result, 'items': items, **item_totals(items)}


def purchasable_variant(session, run, product_id, variant_id):
    env = session.get(db.EnvironmentVersion, run.environment_version_id)
    variant = session.get(catalog.Variant, (env.dataset_snapshot_id, variant_id))
    if variant is None or variant.product_id != product_id:
        return None, rejected('INVALID_VARIANT', 422)
    if not variant.is_available or not variant.is_purchasable:
        return None, rejected('PRODUCT_NOT_PURCHASABLE', 422)
    return variant, None


def purchase_item(session, variant, quantity, origin=None):
    product = session.get(catalog.Product, (variant.dataset_snapshot_id, variant.product_id))
    return PurchaseItem(product_id=variant.product_id, variant_id=variant.variant_id,
        title=product.document['title'], selected_options=variant.document['option_values'],
        quantity=quantity, unit_price_minor=variant.unit_price_minor,
        total_price_minor=variant.unit_price_minor * quantity if variant.unit_price_minor is not None else None,
        currency=variant.currency, origin_placement_id=origin).model_dump(mode='json')


def confirm_purchase(session, run, items, catalog_id, key, request_hash, source):
    totals = item_totals(items)
    single = items[0] if len(items) == 1 else {}
    purchase = db.Purchase(context_id=run.id, run_id=run.run_id, shop_session_id=run.login.id,
        user_id=run.user_id, dataset_snapshot_id=catalog_id, items=items,
        **{field: single.get(field) for field in ('product_id','variant_id','selected_options','quantity','unit_price_minor','origin_placement_id')},
        total_price_minor=totals['total_price_minor'], currency=totals['currency'],
        idempotency_key=key, request_hash=request_hash, purchased_at=db_now(session))
    session.add(purchase)
    session.flush()
    if run.run:
        run.run.state, run.run.ended_at, run.run.end_reason = 'PURCHASED', purchase.purchased_at, 'purchase'
    record_event(session, run, 'purchase_confirmed', {'purchase_id': purchase.id,
        **{field: getattr(purchase,field) for field in ('product_id','variant_id','selected_options','quantity','unit_price_minor','origin_placement_id')},
        'items': items, **totals, 'purchase_source': source})
    return Outcome(purchase_dto(purchase))


class PurchaseService:
    def __init__(self, engine):
        self.engine = engine

    def select_variant(self, credential, product_id, selection: SelectionRequest):
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            run, error = lock_context(session, credential, selection.context_id)
            if error:
                return error
            key = str(selection.client_request_id) if selection.client_request_id else None
            payload = {'product_id':product_id, **selection.model_dump(mode='json')}
            fingerprint = canonical_hash(payload)
            if retry := action_retry(session,run.id,'selection',key,fingerprint): return retry
            if error := guard_running(session, run):
                return error
            if selection.quantity > run.limits['max_quantity']:
                return rejected('INVALID_QUANTITY', 422)
            variant, error = purchasable_variant(session, run, product_id, selection.variant_id)
            if error:
                return error
            state = session.get(db.ProductViewState, (run.id, product_id))
            changed = state is None or (state.variant_id,state.quantity)!=(selection.variant_id,selection.quantity)
            if state is None:
                state = db.ProductViewState(context_id=run.id, run_id=run.run_id, product_id=product_id,
                    dataset_snapshot_id=variant.dataset_snapshot_id, variant_id=variant.variant_id,
                    quantity=selection.quantity)
                session.add(state)
            else:
                state.variant_id, state.quantity = variant.variant_id, selection.quantity
            if changed: record_event(session, run, 'selection_updated', payload)
            result = Outcome({**payload,'unit_price_minor':variant.unit_price_minor,'currency':variant.currency})
            return save_action_receipt(session,run.id,'selection',key,fingerprint,result)

    def rejected_purchase_input(self,credential,code,request_id,context_id=None,idempotency_key=None,payload_hash=None):
        """Record authenticated malformed attempts without retaining raw input."""
        with Session(self.engine) as session,session.begin():
            run,error=lock_context(session,credential,context_id)
            if error:
                return
            key=idempotency_key if idempotency_key and len(idempotency_key)<=160 else None
            if key and payload_hash:
                retry=action_retry(session,run.id,'purchase',key,payload_hash)
                if retry:
                    if retry.error=='IDEMPOTENCY_CONFLICT':
                        record_event(session,run,'shop_request_conflict',{'action':'purchase','code':retry.error},request_id=request_id)
                    return retry
            record_event(session,run,'purchase_requested',{'validation_failed':True,'logical_request_id':key},request_id=request_id)
            guard_running(session,run)
            record_event(session,run,'purchase_rejected',{'code':code},request_id=request_id)
            if key and payload_hash:
                return save_action_receipt(session,run.id,'purchase',key,payload_hash,rejected(code,422))

    def purchase(self, credential, request: PurchaseRequest, idempotency_key):
        if not idempotency_key or len(idempotency_key) > 160:
            return rejected('INVALID_INPUT', 422)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            run, error = lock_context(session, credential, request.context_id)
            if error:
                return error
            # Keep historical purchase request hashes valid; the purchase key is in the header.
            payload = request.model_dump(mode='json',exclude={'client_request_id'})
            request_hash = canonical_hash(payload)
            if retry := action_retry(session,run.id,'purchase',idempotency_key,request_hash): return retry
            existing = session.scalar(select(db.Purchase).where(db.Purchase.context_id == run.id,
                db.Purchase.idempotency_key == idempotency_key))
            if existing is not None and existing.idempotency_key == idempotency_key:
                if existing.request_hash != request_hash:
                    record_event(session,run,'shop_request_conflict',{'action':'purchase','code':'IDEMPOTENCY_CONFLICT'})
                    return rejected('IDEMPOTENCY_CONFLICT')
                return Outcome(purchase_dto(existing))
            record_event(session, run, 'purchase_requested', {**payload,'logical_request_id':idempotency_key})
            error = guard_running(session, run)
            if not error and not run.user_id:
                error = rejected('USER_REQUIRED', 401)
            variant = None
            if not error and request.quantity > run.limits['max_quantity']:
                error = rejected('INVALID_QUANTITY', 422)
            if not error:
                variant, error = purchasable_variant(session, run, request.product_id, request.variant_id)
            if not error and request.origin_placement_id:
                origin = session.get(db.Placement, request.origin_placement_id)
                if origin is None or origin.context_id != run.id or origin.product_id != request.product_id:
                    error = rejected('CROSS_RUN_ACCESS_DENIED', 403)
            if error:
                record_event(session, run, 'purchase_rejected', {'code': error.error})
                return save_action_receipt(session,run.id,'purchase',idempotency_key,request_hash,error)
            item = purchase_item(session, variant, request.quantity, request.origin_placement_id)
            return confirm_purchase(session, run, [item], variant.dataset_snapshot_id,
                                         idempotency_key, request_hash, 'buy_now')

    def abandon(self, credential, context_id):
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            run, error = lock_context(session, credential, context_id)
            if error:
                return error
            if error := guard_running(session, run):
                return error
            if run.run:
                finish(session, run, 'ABANDONED', 'run_abandoned')
            else:
                record_event(session, run, 'shopping_abandoned', {})
            return Outcome({'run_id': run.run_id, 'state': run.state})
