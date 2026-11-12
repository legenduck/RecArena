"""Snapshot-scoped catalog storage. Runtime tables are added by their milestones."""
from datetime import datetime

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, desc,
                        Integer, String, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from recarena_platform.db import Base


class DatasetSnapshot(Base):
    __tablename__ = 'dataset_snapshots'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = 'products'
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey('dataset_snapshots.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB)


class Variant(Base):
    __tablename__ = 'variants'
    dataset_snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    variant_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String)
    unit_price_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    is_available: Mapped[bool]
    is_purchasable: Mapped[bool]
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
        UniqueConstraint('dataset_snapshot_id', 'product_id', 'variant_id'),
        CheckConstraint('unit_price_minor IS NULL OR unit_price_minor >= 0', name='variant_nonnegative_price'),
        CheckConstraint('NOT is_purchasable OR is_available', name='variant_verified_purchase'),
    )


class ReviewSnapshot(Base):
    __tablename__ = 'review_snapshots'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey('dataset_snapshots.id'))
    manifest: Mapped[dict] = mapped_column(JSONB)
    cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('id', 'dataset_snapshot_id'),)


class Review(Base):
    __tablename__ = 'reviews'
    review_snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    product_id: Mapped[str] = mapped_column(String)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['review_snapshot_id', 'dataset_snapshot_id'], ['review_snapshots.id', 'review_snapshots.dataset_snapshot_id']),
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
        Index('ix_reviews_snapshot_product_order', 'review_snapshot_id', 'product_id', desc('timestamp_utc'), 'review_id'),
    )


class ReviewStatistics(Base):
    """Derived once from the complete public review snapshot, never a review page."""
    __tablename__ = 'review_statistics'
    review_snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    rating_counts: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['review_snapshot_id', 'dataset_snapshot_id'], ['review_snapshots.id', 'review_snapshots.dataset_snapshot_id']),
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
        CheckConstraint("jsonb_typeof(rating_counts) = 'array'", name='review_rating_counts_array'),
    )


class HistorySnapshot(Base):
    __tablename__ = 'history_snapshots'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey('dataset_snapshots.id'))
    manifest: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('id', 'dataset_snapshot_id'),)


class HistoricalUser(Base):
    __tablename__ = 'historical_users'
    history_snapshot_id: Mapped[str] = mapped_column(ForeignKey('history_snapshots.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)


class HistoricalInteraction(Base):
    __tablename__ = 'historical_interactions'
    history_snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(String)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['history_snapshot_id', 'dataset_snapshot_id'], ['history_snapshots.id', 'history_snapshots.dataset_snapshot_id']),
        ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']),
        ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
    )


class TaskVersion(Base):
    __tablename__ = 'task_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey('dataset_snapshots.id'))
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('task_id', 'version'), CheckConstraint('version > 0', name='positive_task_version'))
