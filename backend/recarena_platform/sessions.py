"""Script-issued, immutable shopping sessions; ordinary HTTP visits never create Runs."""
import hashlib
import os
import secrets
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from recarena_contracts.artifacts import canonical_hash
from recarena_contracts.layout import from_environment
from recarena_contracts.models import EventEnvelope
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db
from recarena_platform.contexts import Scope, lock_login, current_scope
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.events import db_now, record_event
from recarena_platform.contexts import secret_hash
from recarena_platform.runs import create_run_in_session, finish
from recarena_platform.shopping.purchases import purchase_dto
from recarena_platform.environments import ensure_ready
from recarena_platform.ranking_client import RankingFailure
from recarena_platform.request_context import event_metadata, request_context


def site_settings(session):
    row = session.get(db.SiteSettings, 'shop')
    return row.config if row else {'default_environment_id': None, 'policies': {}}


def session_dto(session, scope):
    purchase = session.scalar(select(db.Purchase).where(db.Purchase.run_id == scope.run_id)) if scope.run else None
    environment = session.get(db.EnvironmentVersion, scope.environment_version_id) if scope.environment_version_id else None
    layout = from_environment(environment.config).layout if environment else None
    cart = session.get(db.Cart, scope.id)
    return {'shop_session_id': scope.login.id, 'context_id': scope.id, 'run_id': scope.run_id,
        'state': scope.state, 'experiment_active': scope.state == 'RUNNING',
        'environment_ready': scope.environment_version_id is not None,
        'max_quantity': scope.limits['max_quantity'], 'purchase': purchase_dto(purchase) if purchase else None,
        'show_abandon': layout.abandon_enabled if layout else False,
        'show_cart': layout.cart_enabled if layout else False,
        'cart_quantity': sum(item['quantity'] for item in cart.items) if cart else 0}


def unscoped_access(session, event_type):
    now = db_now(session)
    event = EventEnvelope(event_id=uuid4(), run_id=None, sequence=1, source='platform_server',
        event_type=event_type, occurred_at=now, received_at=now,
        request_id=request_context.get().get('request_id'), **event_metadata(event_type))
    document = event.model_dump(mode='json')
    session.add(db.Event(event_id=str(event.event_id), sequence=1, source=event.source,
        event_type=event_type, document=document, content_hash=canonical_hash(document)))


class SessionService:
    def __init__(self, engine, ranking=None):
        self.engine, self.ranking = engine, ranking

    def inspect(self, credential, *, present=None):
        with Session(self.engine) as session, session.begin():
            login, error = lock_login(session, credential)
            if error or not login.entry_id:
                unscoped_access(session, 'invalid_session_access' if credential else 'out_of_session')
                return rejected('INVALID_SESSION' if credential else 'SESSION_REQUIRED', 401)
            scope = current_scope(session, login)
            if scope is None or scope.run is None:
                unscoped_access(session, 'invalid_session_access')
                return rejected('INVALID_SESSION', 401)
            record_event(session, scope, 'session_accessed' if scope.state == 'RUNNING' else 'ended_session_access',
                         {'state': scope.state})
            # A terminal DTO permits a receipt/ended screen, never new shopping.
            result = Outcome(session_dto(session, scope))
            return present(session, result) if present else result

    def issue(self, config, request_key=None):
        config = {'v': 1, **config}
        digest = canonical_hash(config)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            if request_key:
                # Serialize retries even when neither request has inserted its session yet.
                key = int.from_bytes(hashlib.sha256(('session-issuance:' + request_key).encode()).digest()[:8], 'big', signed=True)
                session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
                prior = session.scalar(select(db.ShopSession).where(db.ShopSession.issuance_key == request_key))
                if prior:
                    scope = current_scope(session, prior)
                    if scope is None or scope.run.configuration_digest != digest:
                        return rejected('IDEMPOTENCY_CONFLICT')
                    return Outcome(self._issued(prior, scope.run, False))
            env_id = site_settings(session)['policies'].get(config['policy'])
            if not env_id:
                return rejected('UNKNOWN_POLICY', 422)
            env = session.get(db.EnvironmentVersion, env_id)
            if env is None or env.state != 'PUBLISHED':
                return rejected('POLICY_NOT_READY', 422)
            if session.get(catalog.HistoricalUser, (env.history_snapshot_id, config['user_id'])) is None:
                return rejected('UNKNOWN_USER', 422)
            try:
                ensure_ready(session, self.ranking, env, config['user_id'])
                presentation = from_environment(env.config)
            except (KeyError, ValueError, RankingFailure):
                return rejected('POLICY_NOT_READY', 422)
            created = create_run_in_session(session, env_id, config['user_id'])
            if created.error:
                session.rollback()
                return created
            run = session.get(db.Run, created.value['run_id'])
            entry_id = secrets.token_urlsafe(32)
            login = db.ShopSession(credential_hash=secret_hash(entry_id), entry_id=entry_id,
                issuance_key=request_key, user_id=run.user_id, history_snapshot_id=run.history_snapshot_id)
            session.add(login)
            session.flush()
            run.shop_session_id = login.id
            # The creation event was written before its session existed. Assign its session
            # reference inside this same transaction; its research facts remain unchanged.
            for event in session.scalars(select(db.Event).where(db.Event.run_id == run.id)):
                event.shop_session_id = login.id
                event.document = {**event.document, 'shop_session_id': login.id}
                event.content_hash = canonical_hash(event.document)
            run.requested_policy, run.agent_label = config['policy'], config.get('agent')
            run.external_task_id, run.client_run_id = config.get('task_id'), config.get('client_run_id')
            run.entry_config, run.entry_encoding, run.configuration_digest = config, 'api', digest
            run.entry_snapshot = {'environment_version_id': env.id, 'environment_config_hash': env.config_hash,
                'catalog_id': env.dataset_snapshot_id, 'history_id': env.history_snapshot_id,
                'review_id': env.review_snapshot_id,
                'sources': {name: source.model_dump(mode='json') for name, source in presentation.ranking_sources.items()}}
            run.state, run.started_at = 'RUNNING', db_now(session)
            context = db.ShopContext(shop_session_id=login.id, run_id=run.id, user_id=run.user_id,
                history_snapshot_id=run.history_snapshot_id, environment_version_id=env_id)
            session.add(context)
            session.flush()
            login.current_context_id = context.id
            record_event(session, Scope(context, login, run), 'rollout_initialized',
                {'entry_encoding': 'api', 'normalized_entry_config': config, 'applied': run.entry_snapshot})
            return Outcome(self._issued(login, run, True))

    @staticmethod
    def _issued(login, run, created):
        base = os.environ.get('RECARENA_SHOP_URL', 'http://127.0.0.1:5173').rstrip('/')
        return {'session_id': login.entry_id, 'shop_session_id': login.id, 'rollout_id': run.id,
                'entry_url': f'{base}/s/{login.entry_id}/', 'created': created, 'state': run.state}

    def end(self, credential, reason):
        with Session(self.engine) as session, session.begin():
            login, error = lock_login(session, credential)
            if error or not login.entry_id:
                return rejected('INVALID_SESSION', 404)
            scope = current_scope(session, login)
            if scope is None or scope.run is None:
                return rejected('INVALID_SESSION', 404)
            if scope.state == 'RUNNING':
                finish(session, scope, 'CANCELLED', 'run_cancelled', end_reason=reason)
            return Outcome({'rollout_id': scope.run_id, 'state': scope.state, 'end_reason': scope.run.end_reason})
