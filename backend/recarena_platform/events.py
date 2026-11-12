"""Server events and timestamps within the caller's transaction."""
from uuid import uuid4
from sqlalchemy import func, select
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import EventEnvelope
from recarena_contracts.events import RECORDING_METHOD
from recarena_platform.db import runtime as db
from recarena_platform.contexts import Scope


def db_now(session):
    # now()/transaction_timestamp() can precede time spent waiting for the run lock.
    return session.scalar(select(func.clock_timestamp()))


def record_event(session, run, event_type, payload, *, source='platform_server', request_id=None, schema_version='1.0'):
    from recarena_platform.request_context import event_metadata, request_context
    request_id = request_id or request_context.get().get('request_id')
    timestamp = db_now(session)
    scope = run if isinstance(run, Scope) else None
    identifier = scope.run_id if scope else run.id
    envelope = EventEnvelope(schema_version=schema_version,event_id=uuid4(), run_id=identifier, sequence=run.next_sequence,
        recording_method=RECORDING_METHOD,
        occurrence_relative_to_end=('not_applicable' if scope and scope.run is None else
            'after' if (scope.run if scope else run).ended_at else 'before'),
        shop_session_id=scope.login.id if scope else run.shop_session_id,
        context_id=scope.id if scope else None,
        source=source, event_type=event_type, occurred_at=timestamp, received_at=timestamp,
        request_id=request_id, payload=payload, **event_metadata(event_type))
    document = envelope.model_dump(mode='json')
    session.add(db.Event(run_id=identifier, context_id=envelope.context_id, shop_session_id=envelope.shop_session_id,
        event_id=str(envelope.event_id), sequence=run.next_sequence,
        source=source, event_type=event_type, document=document, content_hash=canonical_hash(document)))
    run.next_sequence += 1
    if scope and scope.run and scope.run.first_interaction_at is None and event_type in {
        'search_submitted','product_detail_served','reviews_served','selection_updated','purchase_requested','run_abandoned',
        'cart_item_added','cart_item_updated','cart_item_removed'}:
        scope.run.first_interaction_at = timestamp
