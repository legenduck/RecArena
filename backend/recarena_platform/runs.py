"""Research execution lifecycle; no agent execution or model handling."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.models import RunLimits
from recarena_contracts.events import RECORDING_METHOD
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.contexts import Scope, current_scope
from recarena_platform.events import db_now, record_event
from recarena_platform.outcomes import Outcome, rejected

def finish(session, run, state, event_type, *, end_reason=None):
    owner = run
    run = owner.run if isinstance(owner, Scope) else owner
    if run is None:
        return
    run.state = state
    run.ended_at = db_now(session)
    run.end_reason = end_reason or {'PURCHASED':'purchase','ABANDONED':'explicit_abandonment',
        'CANCELLED':'administrator_cancel','ERROR':'environment_error'}.get(state, state.lower())
    record_event(session, owner, event_type, {'state': state, 'end_reason':run.end_reason})


def guard_running(session, run):
    if isinstance(run, Scope):
        if run.run and run.run.state != 'RUNNING':
            if run.login.entry_id:
                record_event(session, run, 'ended_session_access', {'state': run.state})
            return rejected('RUN_TERMINAL')
        if run.login.current_context_id != run.id:
            return rejected('STALE_CONTEXT')
        if run.environment_version_id is None:
            return rejected('SITE_NOT_CONFIGURED', 503)
        return None
    if run.state != 'RUNNING':
        return rejected('RUN_TERMINAL')
    return None


def create_run_in_session(session, environment_id, user_id, *, task_id=None, limits=None, run_kind='research', comparison=None, agent=None):
    # Replaying a saved comparison must not reactivate its obsolete telemetry window.
    limits = RunLimits.model_validate({k:v for k,v in (limits or {}).items() if k in RunLimits.model_fields})
    environment = session.get(db.EnvironmentVersion, environment_id)
    if environment is None or environment.state != 'PUBLISHED':
        return rejected('ARTIFACT_NOT_READY', 422)
    if environment.config_hash != canonical_hash(environment.config):
        return rejected('ARTIFACT_MISMATCH', 422)
    if session.get(catalog.HistoricalUser, (environment.history_snapshot_id, user_id)) is None:
        return rejected('INVALID_INPUT', 422)
    # This is a control operation. Shopping state mutations below never read task documents.
    task = session.get(catalog.TaskVersion, task_id) if task_id else None
    if task_id and (task is None or task.dataset_snapshot_id != environment.dataset_snapshot_id):
        return rejected('ARTIFACT_MISMATCH', 422)
    if task is not None and task.document['validation_status']!='VALIDATED':
        return rejected('ARTIFACT_NOT_READY',422)
    run = db.Run(environment_version_id=environment_id, user_id=user_id,
        recording_method=RECORDING_METHOD,
        history_snapshot_id=environment.history_snapshot_id, task_version_id=task_id,
        limits=limits.model_dump(), run_kind=run_kind,
        **(comparison or {}),
        connection={'agent_declaration':agent} if agent else {})
    session.add(run)
    session.flush()
    record_event(session, run, 'run_created', {'environment_version_id': environment_id,
        'user_id': user_id, 'limits': run.limits, 'run_kind': run_kind, 'connection': run.connection, **(comparison or {})})
    return Outcome({'run_id': run.id, 'state': run.state,
                    'agent_task': {'goal': task.document['agent_goal']} if task else None, **(comparison or {})})


class RunService:
    def __init__(self, engine):
        self.engine = engine

    def create_run(self, environment_id, user_id, *, task_id=None, limits=None, run_kind='research'):
        limits = RunLimits.model_validate(limits or {})
        if run_kind not in {'research', 'preview'}:
            return rejected('INVALID_INPUT', 422)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            return create_run_in_session(session, environment_id, user_id, task_id=task_id,
                limits=limits.model_dump(), run_kind=run_kind)

    def start_prepared(self, run_id, shop_session_id):
        """Optional Control path for existing prepared comparisons, never a URL prerequisite."""
        with Session(self.engine) as session, session.begin():
            login = session.scalar(select(db.ShopSession).where(db.ShopSession.id == shop_session_id).with_for_update(key_share=True))
            if login is None or login.revoked:
                return rejected('INVALID_SESSION', 404)
            if login.entry_id is not None:
                return rejected('SESSION_ALREADY_BOUND')
            active = current_scope(session, login)
            if active and active.state == 'RUNNING':
                return rejected('ACTIVE_ROLLOUT_CONFLICT')
            run = session.scalar(select(db.Run).where(db.Run.id == run_id).with_for_update())
            if run is None: return rejected('RESULT_NOT_FOUND', 404)
            if run.state != 'READY': return rejected('RUN_TERMINAL')
            if (login.user_id, login.history_snapshot_id) != (run.user_id, run.history_snapshot_id):
                return rejected('USER_MISMATCH')
            context = db.ShopContext(shop_session_id=login.id,run_id=run.id,user_id=run.user_id,
                history_snapshot_id=run.history_snapshot_id,environment_version_id=run.environment_version_id)
            session.add(context)
            session.flush()
            login.current_context_id = context.id
            run.shop_session_id, run.state, run.started_at = login.id, 'RUNNING', db_now(session)
            record_event(session,Scope(context,login,run),'run_started',{'state':run.state},source='operator')
            return Outcome({'run_id':run.id,'shop_session_id':login.id,'context_id':context.id,'state':run.state})

    def cancel(self, run_id):
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.get(db.Run, run_id)
            if existing and existing.shop_session_id:
                session.scalar(select(db.ShopSession).where(db.ShopSession.id == existing.shop_session_id).with_for_update())
            run = session.scalar(select(db.Run).where(db.Run.id == run_id).with_for_update().execution_options(populate_existing=True))
            if run is None:
                return rejected('INVALID_INPUT', 404)
            if run.state not in {'READY', 'RUNNING'}:
                return rejected('RUN_TERMINAL')
            finish(session, run, 'CANCELLED', 'run_cancelled')
            record_event(session, run, 'operator_cancelled', {'run_id': run.id}, source='operator')
            session.add(db.OperatorAuditEvent(action='run_cancelled',target_id=run.id,document={'state':run.state}))
            return Outcome({'run_id': run.id, 'state': run.state})
