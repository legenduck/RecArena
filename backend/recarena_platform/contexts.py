"""Immutable shopping request identity, independent from optional experiments."""
import hashlib
from dataclasses import dataclass
from sqlalchemy import select
from recarena_contracts.models import RunLimits
from recarena_platform.db import runtime as db


@dataclass
class Scope:
    context: db.ShopContext
    login: db.ShopSession
    run: db.Run | None

    @property
    def id(self): return self.context.id
    @property
    def run_id(self): return self.run.id if self.run else None
    @property
    def user_id(self): return self.context.user_id
    @property
    def history_snapshot_id(self): return self.context.history_snapshot_id
    @property
    def environment_version_id(self): return self.context.environment_version_id
    @property
    def limits(self): return self.run.limits if self.run else RunLimits().model_dump()
    @property
    def state(self): return self.run.state if self.run else 'GENERAL'
    @property
    def next_sequence(self): return self.run.next_sequence if self.run else self.context.next_sequence
    @next_sequence.setter
    def next_sequence(self, value):
        if self.run: self.run.next_sequence = value
        else: self.context.next_sequence = value


def secret_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def lock_login(session, credential):
    from recarena_platform.outcomes import rejected
    from recarena_platform.events import db_now
    if not credential: return None, rejected('INVALID_SESSION', 401)
    # Serialize session changes without blocking FK references from evaluation events.
    # A full UPDATE lock here could deadlock with the evaluator holding the Run.
    login = session.scalar(select(db.ShopSession).where(db.ShopSession.credential_hash == secret_hash(credential)).with_for_update(key_share=True))
    if login is None or login.revoked: return None, rejected('INVALID_SESSION', 401)
    login.last_seen_at = db_now(session)
    return login, None


def current_scope(session, login):
    context = session.get(db.ShopContext, login.current_context_id) if login.current_context_id else None
    if context is None or context.shop_session_id != login.id: return None
    run = session.scalar(select(db.Run).where(db.Run.id == context.run_id).with_for_update()) if context.run_id else None
    return Scope(context, login, run)


def lock_context(session, credential, context_id, *, telemetry=False):
    from recarena_platform.outcomes import rejected
    login, error = lock_login(session, credential)
    if error: return None, error
    if not context_id: return None, rejected('MISSING_CONTEXT', 422)
    context = session.get(db.ShopContext, context_id)
    if context is None or context.shop_session_id != login.id:
        return None, rejected('CROSS_SESSION_ACCESS_DENIED', 403)
    run = session.scalar(select(db.Run).where(db.Run.id == context.run_id).with_for_update()) if context.run_id else None
    return Scope(context, login, run), None
