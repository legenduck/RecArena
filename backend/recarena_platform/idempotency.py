"""Same request receipts; repeated shopping actions keep separate keys."""
from recarena_platform.db import runtime as db
from recarena_platform.outcomes import Outcome, rejected

def action_retry(session, context_id, action, key, request_hash):
    if key is None: return None
    receipt = session.get(db.ShopActionReceipt,(context_id,action,key))
    if receipt is None: return None
    return Outcome(**receipt.response) if receipt.request_hash==request_hash else rejected('IDEMPOTENCY_CONFLICT')


def save_action_receipt(session, context_id, action, key, request_hash, result):
    if key is not None:
        session.add(db.ShopActionReceipt(context_id=context_id,action=action,request_key=key,
            request_hash=request_hash,response={'value':result.value,'error':result.error,'status':result.status}))
    return result
