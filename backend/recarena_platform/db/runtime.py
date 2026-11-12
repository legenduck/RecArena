"""Run-owned mutable state, with final purchases and events committed together."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
                        Integer, String, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from recarena_platform.db import Base


def new_id():
    return str(uuid4())


class EnvironmentVersion(Base):
    __tablename__ = 'environment_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    state: Mapped[str] = mapped_column(String, default='DRAFT')
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey('dataset_snapshots.id'))
    review_snapshot_id: Mapped[str] = mapped_column(String)
    history_snapshot_id: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("state IN ('DRAFT', 'VALIDATED', 'PUBLISHED')", name='environment_state_valid'),
        ForeignKeyConstraint(['review_snapshot_id', 'dataset_snapshot_id'], ['review_snapshots.id', 'review_snapshots.dataset_snapshot_id']),
        ForeignKeyConstraint(['history_snapshot_id', 'dataset_snapshot_id'], ['history_snapshots.id', 'history_snapshots.dataset_snapshot_id']),
    )


class Run(Base):
    __tablename__ = 'runs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    environment_version_id: Mapped[str] = mapped_column(ForeignKey('environment_versions.id'))
    user_id: Mapped[str] = mapped_column(String)
    history_snapshot_id: Mapped[str] = mapped_column(String)
    task_version_id: Mapped[str | None] = mapped_column(ForeignKey('task_versions.id'))
    state: Mapped[str] = mapped_column(String, default='READY')
    run_kind: Mapped[str] = mapped_column(String, default='research')
    limits: Mapped[dict] = mapped_column(JSONB)
    connection: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sequence: Mapped[int] = mapped_column(BigInteger, default=1)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey('experiments.id'))
    condition_id: Mapped[str | None] = mapped_column(String)
    pair_id: Mapped[str | None] = mapped_column(String)
    repetition: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    shop_session_id: Mapped[str | None] = mapped_column(ForeignKey('shop_sessions.id', use_alter=True, name='run_shop_session_fk'))
    requested_policy: Mapped[str | None] = mapped_column(String, index=True)
    agent_label: Mapped[str | None] = mapped_column(String, index=True)
    external_task_id: Mapped[str | None] = mapped_column(String, index=True)
    client_run_id: Mapped[str | None] = mapped_column(String, index=True)
    entry_encoding: Mapped[str | None] = mapped_column(String)
    entry_config: Mapped[dict | None] = mapped_column(JSONB)
    entry_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    configuration_digest: Mapped[str | None] = mapped_column(String(64))
    first_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_method: Mapped[str | None] = mapped_column(String)
    end_reason: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']),
        CheckConstraint("state IN ('READY','RUNNING','PURCHASED','ABANDONED','TIMED_OUT','CANCELLED','ERROR','EXPIRED')", name='run_state_valid'),
        CheckConstraint("run_kind IN ('research','preview')", name='run_kind_valid'),
        ForeignKeyConstraint(['condition_id','experiment_id'], ['experiment_conditions.id','experiment_conditions.experiment_id']),
        ForeignKeyConstraint(['pair_id','experiment_id'], ['experiment_pairs.id','experiment_pairs.experiment_id']),
        CheckConstraint("(experiment_id IS NULL AND condition_id IS NULL AND pair_id IS NULL AND repetition IS NULL AND seed IS NULL) OR "
                        "(experiment_id IS NOT NULL AND condition_id IS NOT NULL AND pair_id IS NOT NULL AND repetition IS NOT NULL AND repetition > 0 AND seed IS NOT NULL)", name='run_comparison_fields'),
        UniqueConstraint('experiment_id','condition_id','pair_id','repetition', name='run_comparison_unique'),
    )


class RunnerTelemetryRecord(Base):
    """Historical external submissions; no active writer or upload API."""
    __tablename__ = 'runner_telemetry'
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'),primary_key=True)
    submission_id: Mapped[str] = mapped_column(String,primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSONB)
    sequence: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())


class RunAttachment(Base):
    """Historical attachments retained for authenticated download and export."""
    __tablename__ = 'run_attachments'
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'),primary_key=True)
    attachment_id: Mapped[str] = mapped_column(String,primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB)
    storage_path: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())


class BrowserProfile(Base):
    """Historical browser metadata only; never gates or changes current Runs."""
    __tablename__ = 'browser_profiles'
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'),primary_key=True)
    profile_id: Mapped[str] = mapped_column(String,unique=True)
    runtime: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String,default='REGISTERED')
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (CheckConstraint("state IN ('REGISTERED','CLOSED','FAILED')",name='browser_profile_state'),)


class ShopSession(Base):
    __tablename__ = 'shop_sessions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    entry_id: Mapped[str | None] = mapped_column(String(43), unique=True)
    issuance_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    user_id: Mapped[str | None] = mapped_column(String)
    history_snapshot_id: Mapped[str | None] = mapped_column(String)
    current_context_id: Mapped[str | None] = mapped_column(ForeignKey('shop_contexts.id', use_alter=True, name='session_current_context_fk'))
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']),)


class ShopContext(Base):
    """Immutable ownership/condition for a browser's page and request lineage."""
    __tablename__ = 'shop_contexts'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    shop_session_id: Mapped[str] = mapped_column(ForeignKey('shop_sessions.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), unique=True)
    user_id: Mapped[str | None] = mapped_column(String)
    history_snapshot_id: Mapped[str | None] = mapped_column(String)
    environment_version_id: Mapped[str | None] = mapped_column(ForeignKey('environment_versions.id'))
    next_sequence: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('id', 'run_id'),
        ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']),)


class Cart(Base):
    __tablename__ = 'carts'
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    items: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    __table_args__ = (CheckConstraint('version >= 0', name='cart_version_valid'),
        CheckConstraint("jsonb_typeof(items) = 'array'", name='cart_items_array'))


class SiteSettings(Base):
    __tablename__ = 'site_settings'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB)


class ShoppingView(Base):
    __tablename__ = 'shopping_views'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'), index=True)
    kind: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BootstrapReceipt(Base):
    __tablename__ = 'bootstrap_receipts'
    shop_session_id: Mapped[str] = mapped_column(ForeignKey('shop_sessions.id'), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    configuration_digest: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'))


class ShopActionReceipt(Base):
    __tablename__ = 'shop_action_receipts'
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'), primary_key=True)
    action: Mapped[str] = mapped_column(String, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)


class CandidateSet(Base):
    __tablename__ = 'candidate_sets'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB)


class ResultSnapshot(Base):
    __tablename__ = 'result_snapshots'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), index=True)
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'))
    candidate_set_id: Mapped[str] = mapped_column(ForeignKey('candidate_sets.id'))
    client_request_id: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('id', 'run_id'), UniqueConstraint('id', 'context_id'), UniqueConstraint('context_id', 'client_request_id'))


class Placement(Base):
    __tablename__ = 'placements'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'))
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'))
    result_snapshot_id: Mapped[str] = mapped_column(String)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    product_id: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['result_snapshot_id', 'run_id'], ['result_snapshots.id', 'result_snapshots.run_id']),
        ForeignKeyConstraint(['result_snapshot_id', 'context_id'], ['result_snapshots.id', 'result_snapshots.context_id']),
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
        UniqueConstraint('id', 'run_id'),
        UniqueConstraint('id', 'context_id'),
    )


class ProductViewState(Base):
    __tablename__ = 'product_view_states'
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'))
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    variant_id: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id', 'variant_id'], ['variants.dataset_snapshot_id', 'variants.product_id', 'variants.variant_id']),
        CheckConstraint('quantity BETWEEN 1 AND 99', name='selection_quantity_valid'),
    )


class Purchase(Base):
    __tablename__ = 'purchases'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), unique=True)
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'))
    shop_session_id: Mapped[str] = mapped_column(ForeignKey('shop_sessions.id'))
    user_id: Mapped[str] = mapped_column(String)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    product_id: Mapped[str | None] = mapped_column(String)
    variant_id: Mapped[str | None] = mapped_column(String)
    selected_options: Mapped[dict | None] = mapped_column(JSONB)
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    total_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    origin_placement_id: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[list | None] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id', 'variant_id'], ['variants.dataset_snapshot_id', 'variants.product_id', 'variants.variant_id']),
        ForeignKeyConstraint(['origin_placement_id', 'run_id'], ['placements.id', 'placements.run_id']),
        ForeignKeyConstraint(['origin_placement_id', 'context_id'], ['placements.id', 'placements.context_id']),
        UniqueConstraint('context_id', 'idempotency_key'),
        CheckConstraint('quantity BETWEEN 1 AND 99', name='purchase_quantity_valid'),
        CheckConstraint("(product_id IS NOT NULL AND variant_id IS NOT NULL AND quantity IS NOT NULL AND currency IS NOT NULL AND jsonb_typeof(selected_options) = 'object' AND (items IS NULL OR (jsonb_typeof(items) = 'array' AND jsonb_array_length(items) = 1))) OR (product_id IS NULL AND variant_id IS NULL AND quantity IS NULL AND unit_price_minor IS NULL AND items IS NOT NULL AND jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 1)", name='purchase_shape_valid'),
        CheckConstraint("(items IS NOT NULL AND jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 1 "
            "AND product_id IS NULL AND variant_id IS NULL AND quantity IS NULL AND unit_price_minor IS NULL "
            "AND (total_price_minor IS NULL OR (total_price_minor >= 0 AND currency IS NOT NULL))) OR "
            '(unit_price_minor IS NULL AND total_price_minor IS NULL) OR '
            '(unit_price_minor IS NOT NULL AND total_price_minor IS NOT NULL AND unit_price_minor >= 0 '
            'AND total_price_minor = unit_price_minor * quantity)', name='purchase_amount_valid'),
    )


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'))
    context_id: Mapped[str | None] = mapped_column(ForeignKey('shop_contexts.id'))
    shop_session_id: Mapped[str | None] = mapped_column(ForeignKey('shop_sessions.id'))
    event_id: Mapped[str] = mapped_column(String)
    sequence: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('run_id', 'source', 'event_id'), UniqueConstraint('run_id', 'sequence'),
                     UniqueConstraint('context_id', 'source', 'event_id'), UniqueConstraint('context_id', 'sequence'))


class Experiment(Base):
    __tablename__ = 'experiments'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))
    warnings: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentCondition(Base):
    __tablename__ = 'experiment_conditions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey('experiments.id'))
    environment_version_id: Mapped[str] = mapped_column(ForeignKey('environment_versions.id'))
    label: Mapped[str] = mapped_column(String)
    __table_args__ = (UniqueConstraint('id','experiment_id'), UniqueConstraint('experiment_id','label'))


class ExperimentPair(Base):
    __tablename__ = 'experiment_pairs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey('experiments.id'))
    user_id: Mapped[str] = mapped_column(String)
    task_version_id: Mapped[str] = mapped_column(ForeignKey('task_versions.id'))
    __table_args__ = (UniqueConstraint('id','experiment_id'), UniqueConstraint('experiment_id','user_id','task_version_id'))


class RegisteredArtifact(Base):
    __tablename__ = 'registered_artifacts'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSONB)
    manifest_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyVersion(Base):
    __tablename__ = 'policy_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))


class OperatorAuditEvent(Base):
    __tablename__ = 'operator_audit_events'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QualifiedImpression(Base):
    __tablename__ = 'qualified_impressions'
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'))
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'),primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64),primary_key=True)
    event_id: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSONB)


class ClientEventReceipt(Base):
    __tablename__ = 'client_event_receipts'
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'))
    context_id: Mapped[str] = mapped_column(ForeignKey('shop_contexts.id'),primary_key=True)
    event_id: Mapped[str] = mapped_column(String,primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    disposition: Mapped[str] = mapped_column(String)


class ExportRecord(Base):
    __tablename__ = 'exports'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=new_id)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey('experiments.id'))
    scope: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String,default='PENDING')
    directory: Mapped[str | None] = mapped_column(String)
    archive_path: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())
    __table_args__ = (CheckConstraint("state IN ('PENDING','COMPLETED','FAILED')",name='export_state_valid'),)
