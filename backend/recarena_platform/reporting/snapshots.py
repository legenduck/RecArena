"""Read export rows lazily from one repeatable database snapshot."""
from contextlib import contextmanager
from datetime import datetime
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recarena_platform.db import catalog, runtime as db
from recarena_platform.catalog.artifacts import saved_resources
from recarena_platform.environments import public_environment
from recarena_platform.shopping.purchases import purchase_dto
from recarena_platform.reporting.comparisons import describe
from recarena_platform.reporting.queries import filtered_runs

RUN_FIELDS=('id','environment_version_id','experiment_id','condition_id','pair_id','user_id','history_snapshot_id','task_version_id',
    'run_kind','state','repetition','seed','started_at','ended_at','limits','connection',
    'shop_session_id','requested_policy','agent_label','external_task_id','client_run_id','entry_encoding','entry_config',
    'entry_snapshot','first_interaction_at','end_reason','created_at','recording_method')
PURCHASE_FIELDS=('id','run_id','context_id','shop_session_id','user_id','product_id','variant_id','selected_options','quantity','unit_price_minor','total_price_minor','currency','origin_placement_id','purchased_at','items','total_quantity','totals_by_currency')
FETCH_ROWS=100


def json_value(value):
    return json.loads(json.dumps(value,default=lambda value:value.isoformat() if isinstance(value,datetime) else str(value),allow_nan=False))


@contextmanager
def open_snapshot(engine,experiment_id=None,run_ids=None,filters=None):
    """All iterators must be consumed inside this context, including on failure."""
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        with Session(connection) as session,session.begin():
            data_as_of=session.scalar(text('SELECT clock_timestamp()'))
            experiment=session.get(db.Experiment,experiment_id) if experiment_id else None
            if experiment_id and experiment is None: raise KeyError('Unknown experiment')
            query=filtered_runs(filters)
            if experiment_id: query=query.where(db.Run.experiment_id==experiment_id)
            if run_ids is not None: query=query.where(db.Run.id.in_(run_ids))
            selected=query.with_only_columns(db.Run.id)
            identifiers=list(session.scalars(selected.order_by(db.Run.id)))
            if run_ids is not None and set(identifiers)!=set(run_ids): raise KeyError('Unknown rollout')
            environment_ids=set(session.scalars(query.with_only_columns(db.Run.environment_version_id).distinct()))
            if experiment_id:
                environment_ids.update(session.scalars(select(db.ExperimentCondition.environment_version_id).where(db.ExperimentCondition.experiment_id==experiment_id)))
            environments=[public_environment(session.get(db.EnvironmentVersion,key)) for key in sorted(environment_ids)]
            task_ids=query.with_only_columns(db.Run.task_version_id).where(db.Run.task_version_id.is_not(None))
            tasks={row.id:row.document for row in session.scalars(select(catalog.TaskVersion).where(catalog.TaskVersion.id.in_(task_ids)))}

            def rows(statement):
                return session.scalars(statement.execution_options(yield_per=FETCH_ROWS))

            def runs():
                for row in rows(query.order_by(db.Run.id)):
                    value={key:getattr(row,key) for key in RUN_FIELDS}
                    yield json_value(value)

            def rankings():
                statement=select(db.ResultSnapshot.id,db.ResultSnapshot.run_id,db.ResultSnapshot.document,db.CandidateSet.document).join(
                    db.CandidateSet,db.CandidateSet.id==db.ResultSnapshot.candidate_set_id).where(
                    db.ResultSnapshot.run_id.in_(selected)).order_by(db.ResultSnapshot.id)
                for key,run_id,document,candidates in session.execute(statement.execution_options(yield_per=FETCH_ROWS)):
                    yield {'result_snapshot_id':key,'run_id':run_id,**document,'candidate_set':candidates}

            latest=session.scalars(select(db.RunnerTelemetryRecord).where(db.RunnerTelemetryRecord.run_id.in_(selected))
                .distinct(db.RunnerTelemetryRecord.run_id).order_by(db.RunnerTelemetryRecord.run_id,db.RunnerTelemetryRecord.sequence.desc()))
            yield {
                'experiment':json_value(describe(session,experiment)) if experiment else None,
                'scope':json_value({'experiment_id':experiment_id,'run_ids':identifiers,'filters':filters or {},'data_as_of':data_as_of}),
                'environments':environments,'tasks':tasks,'artifacts':saved_resources(session),
                'runs':runs(),
                'purchases':(json_value({**purchase_dto(p),'shop_session_id':p.shop_session_id,'user_id':p.user_id})
                    for p in rows(select(db.Purchase).where(db.Purchase.run_id.in_(selected)).order_by(db.Purchase.id))),
                'events':rows(select(db.Event.document).where(db.Event.run_id.in_(selected)).order_by(db.Event.run_id,db.Event.sequence)),
                'rankings':rankings(),
                'placements':({'placement_id':p.id,'run_id':p.run_id,'result_snapshot_id':p.result_snapshot_id,'product_id':p.product_id,**p.document}
                    for p in rows(select(db.Placement).where(db.Placement.run_id.in_(selected)).order_by(db.Placement.id))),
                'telemetry':{r.run_id:r.document for r in latest},
                'telemetry_submissions':(json_value({'run_id':r.run_id,'sequence':r.sequence,'received_at':r.received_at,**r.document})
                    for r in rows(select(db.RunnerTelemetryRecord).where(db.RunnerTelemetryRecord.run_id.in_(selected)).order_by(db.RunnerTelemetryRecord.run_id,db.RunnerTelemetryRecord.sequence))),
                'attachments':({'run_id':a.run_id,'storage_path':a.storage_path,**a.document}
                    for a in rows(select(db.RunAttachment).where(db.RunAttachment.run_id.in_(selected)).order_by(db.RunAttachment.run_id,db.RunAttachment.attachment_id)))}
