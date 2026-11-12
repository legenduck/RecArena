"""Transactional client-event ingestion, ownership and measurement-key dedup."""
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import EventEnvelope
from recarena_contracts.events import RECORDING_METHOD
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.events import db_now, record_event
from recarena_platform.contexts import lock_context


def batch_records(session,run,events,environment):
    """Fetch referenced rows once; membership checks below still apply per event."""
    snapshot_ids={e.payload['result_snapshot_id'] for e in events if e.payload.get('result_snapshot_id')}
    placement_ids={e.payload['placement_id'] for e in events if e.payload.get('placement_id')}
    placement_ids.update(i['placement_id'] for e in events if e.event_type=='item_list_rendered' for i in e.payload['items'])
    product_ids={e.payload['product_id'] for e in events if e.payload.get('product_id')}
    presentations={str(e.payload['list_presentation_id']) for e in events if e.event_type=='item_list_rendered'}
    snapshots=set(session.scalars(select(db.ResultSnapshot.id).where(db.ResultSnapshot.context_id==run.id,
        db.ResultSnapshot.id.in_(snapshot_ids)))) if snapshot_ids else set()
    placements={r.id:r for r in session.scalars(select(db.Placement).where(db.Placement.context_id==run.id,
        db.Placement.id.in_(placement_ids)))} if placement_ids else {}
    products=set(session.scalars(select(catalog.Product.product_id).where(
        catalog.Product.dataset_snapshot_id==environment.dataset_snapshot_id,catalog.Product.product_id.in_(product_ids)))) if environment and product_ids else set()
    receipts={r.event_id:r for r in session.scalars(select(db.ClientEventReceipt).where(
        db.ClientEventReceipt.context_id==run.id,db.ClientEventReceipt.event_id.in_([str(e.event_id) for e in events])))}
    payload=db.Event.document['payload']
    prior=set(session.scalars(select(payload['list_presentation_id'].astext).where(db.Event.context_id==run.id,
        db.Event.event_type=='item_list_rendered',payload['list_presentation_id'].astext.in_(presentations)))) if presentations else set()
    conditions=[]
    list_snapshots={e.payload['result_snapshot_id'] for e in events if e.event_type in {'item_list_rendered','result_page_changed','section_page_changed'}}
    review_products={e.payload['product_id'] for e in events if e.event_type=='reviews_rendered'}
    if list_snapshots:
        conditions.append(and_(db.Event.event_type=='items_served',payload['result_snapshot_id'].astext.in_(list_snapshots)))
    if review_products:
        conditions.append(and_(db.Event.event_type=='reviews_served',payload['product_id'].astext.in_(review_products)))
    lists,sections,pages,reviews=set(),set(),set(),set()
    if conditions:
        for kind,snapshot,block,page,section,positions,product,offset,review_ids in session.execute(select(
                db.Event.event_type,payload['result_snapshot_id'].astext,payload['block_id'].astext,
                payload['main_page'].as_integer(),payload['section_page'].as_integer(),payload['placement_ids'],
                payload['product_id'].astext,payload['offset'].as_integer(),payload['review_ids']).where(
                db.Event.context_id==run.id,or_(*conditions)).distinct()):
            if kind=='items_served' and None not in (snapshot,block,page,section) and positions is not None:
                key=(snapshot,block,page,section)
                lists.add((*key,tuple(positions)));sections.add(key);pages.add((snapshot,page))
            elif kind=='reviews_served' and product is not None and offset is not None and review_ids is not None:
                reviews.add((product,offset,tuple(review_ids)))
    return snapshots,placements,products,receipts,prior,lists,sections,pages,reviews


class ClientEventService:
    def __init__(self,engine,request_id):
        self.engine,self.request_id = engine,request_id

    def batch(self,credential,body):
        with Session(self.engine) as session,session.begin():
            contexts = {event.context_id for event in body.events}
            if len(contexts) != 1:
                return rejected('MIXED_EVENT_CONTEXT', 422)
            run,error = lock_context(session,credential,next(iter(contexts)),telemetry=True)
            if error:
                return error
            now = db_now(session)
            late = run.login.current_context_id != run.id or (run.run is not None and run.state!='RUNNING')
            environment = session.get(db.EnvironmentVersion,run.environment_version_id) if run.environment_version_id else None
            snapshots,placements,products,previous_receipts,prior_lists,served_lists,served_sections,served_pages,served_reviews = batch_records(session,run,body.events,environment)
            accepted,duplicates = [],[]
            pending = []
            receipts = {}
            within_batch = {}
            for event in body.events:
                original = event.model_dump(mode='json')
                if event.view_id is None:
                    original.pop('view_id')  # old receipt hashes predate separate document/view identifiers
                if event.recording_method is None:
                    original.pop('recording_method')  # omit unset optional metadata from receipt hashes
                content_hash = canonical_hash(original)
                identifier = str(event.event_id)
                previous = previous_receipts.get(identifier)
                previous_hash = previous.content_hash if previous else within_batch.get(identifier)
                if previous_hash:
                    if previous_hash!=content_hash:
                        record_event(session,run,'client_event_conflict',{'event_id':identifier},request_id=self.request_id)
                        return rejected('IDEMPOTENCY_CONFLICT',409)
                    duplicates.append(identifier)
                    continue
                payload = event.payload
                if payload.get('result_snapshot_id'):
                    if payload['result_snapshot_id'] not in snapshots:
                        return rejected('CROSS_RUN_ACCESS_DENIED',403)
                if payload.get('placement_id'):
                    placement = placements.get(payload['placement_id'])
                    if (placement is None or placement.context_id!=run.id or placement.result_snapshot_id!=payload['result_snapshot_id']
                            or placement.document['block_id']!=payload['block_id']):
                        return rejected('CROSS_RUN_ACCESS_DENIED',403)
                if payload.get('product_id') and payload['product_id'] not in products:
                    return rejected('RESULT_NOT_FOUND',404)
                if event.event_type == 'item_list_rendered':
                    # A list must be an actual issued block, not the complete candidate set.
                    expected = [item['placement_id'] for item in payload['items']]
                    key=(payload['result_snapshot_id'],payload['block_id'],payload['main_page'],payload['section_page'])
                    if (*key,tuple(expected)) not in served_lists: return rejected('INVALID_LIST_PRESENTATION',422)
                    for item in payload['items']:
                        placement = placements.get(item['placement_id'])
                        if placement is None or placement.context_id!=run.id or placement.product_id!=item['product_id']:
                            return rejected('CROSS_RUN_ACCESS_DENIED',403)
                    if str(payload['list_presentation_id']) in prior_lists:
                        return rejected('PRESENTATION_ID_CONFLICT',409)
                    prior_lists.add(str(payload['list_presentation_id']))
                if event.event_type == 'reviews_rendered':
                    if (payload['product_id'],payload['offset'],tuple(payload['review_ids'])) not in served_reviews:
                        return rejected('INVALID_REVIEW_DISPLAY',422)
                if event.event_type in {'result_page_changed','section_page_changed'}:
                    if event.event_type=='section_page_changed':
                        issued=(payload['result_snapshot_id'],payload['block_id'],payload['main_page'],payload['section_page']) in served_sections
                    else:
                        issued=(payload['result_snapshot_id'],payload['main_page']) in served_pages
                    if not issued:
                        return rejected('INVALID_INPUT',422)
                within_batch[identifier]=content_hash
                receipts[identifier]=(content_hash,'ACCEPTED')
                pending.append((event,content_hash))
            for identifier,(content_hash,disposition) in receipts.items():
                session.add(db.ClientEventReceipt(context_id=run.id,run_id=run.run_id,event_id=identifier,content_hash=content_hash,disposition=disposition))
            for event,content_hash in pending:
                from recarena_platform.request_context import event_metadata
                envelope = EventEnvelope(schema_version='2.0' if event.view_id else '1.0',
                    event_id=event.event_id,run_id=run.run_id,context_id=run.id,shop_session_id=run.login.id,sequence=run.next_sequence,
                    recording_method=event.recording_method,
                    occurrence_relative_to_end='not_applicable' if run.run is None else 'unknown' if run.state!='RUNNING' else 'before',
                    source='shop_client',event_type=event.event_type,occurred_at=event.occurred_at,received_at=now,
                    request_id=self.request_id,page_instance_id=str(event.page_instance_id),client_sequence=event.client_sequence,
                    page_instance_kind='document' if event.view_id else 'legacy_view',
                    view_id=str(event.view_id) if event.view_id else None,
                    payload=event.payload,late_received=late,**event_metadata(event.event_type))
                session.add(db.Event(run_id=run.run_id,context_id=run.id,shop_session_id=run.login.id,event_id=str(event.event_id),sequence=run.next_sequence,source='shop_client',
                    event_type=event.event_type,document=envelope.model_dump(mode='json'),content_hash=content_hash))
                run.next_sequence+=1
                if run.run and run.run.first_interaction_at is None and event.recording_method==RECORDING_METHOD and event.event_type in {'item_list_rendered','product_clicked','reviews_rendered'}:
                    run.run.first_interaction_at=now
                accepted.append(str(event.event_id))
            return Outcome({'accepted_event_ids':accepted,'duplicate_event_ids':duplicates,'late_received':late})
