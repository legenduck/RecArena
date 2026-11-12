"""Snapshot-scoped products, real variants, reviews, fixed histories and private tasks."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('products',
        sa.Column('dataset_snapshot_id', sa.String(), sa.ForeignKey('dataset_snapshots.id'), primary_key=True),
        sa.Column('product_id', sa.String(), primary_key=True),
        sa.Column('document', postgresql.JSONB(), nullable=False))
    op.create_table('variants',
        sa.Column('dataset_snapshot_id', sa.String(), primary_key=True),
        sa.Column('variant_id', sa.String(), primary_key=True),
        sa.Column('product_id', sa.String(), nullable=False),
        sa.Column('unit_price_minor', sa.Integer()),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False),
        sa.Column('is_purchasable', sa.Boolean(), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']),
        sa.UniqueConstraint('dataset_snapshot_id', 'product_id', 'variant_id'),
        sa.CheckConstraint('unit_price_minor IS NULL OR unit_price_minor >= 0', name='variant_nonnegative_price'),
        sa.CheckConstraint('NOT is_purchasable OR (is_available AND unit_price_minor IS NOT NULL)', name='variant_verified_purchase'))
    op.create_table('review_snapshots',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('dataset_snapshot_id', sa.String(), sa.ForeignKey('dataset_snapshots.id'), nullable=False),
        sa.Column('manifest', postgresql.JSONB(), nullable=False),
        sa.Column('cutoff', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('id', 'dataset_snapshot_id'))
    op.create_table('reviews',
        sa.Column('review_snapshot_id', sa.String(), primary_key=True),
        sa.Column('review_id', sa.String(), primary_key=True),
        sa.Column('dataset_snapshot_id', sa.String(), nullable=False),
        sa.Column('product_id', sa.String(), nullable=False),
        sa.Column('timestamp_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['review_snapshot_id', 'dataset_snapshot_id'], ['review_snapshots.id', 'review_snapshots.dataset_snapshot_id']),
        sa.ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']))
    op.create_index('ix_reviews_timestamp_utc', 'reviews', ['timestamp_utc'])
    op.create_table('history_snapshots',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('dataset_snapshot_id', sa.String(), sa.ForeignKey('dataset_snapshots.id'), nullable=False),
        sa.Column('manifest', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('id', 'dataset_snapshot_id'))
    op.create_table('historical_users',
        sa.Column('history_snapshot_id', sa.String(), sa.ForeignKey('history_snapshots.id'), primary_key=True),
        sa.Column('user_id', sa.String(), primary_key=True))
    op.create_table('historical_interactions',
        sa.Column('history_snapshot_id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), primary_key=True),
        sa.Column('product_id', sa.String(), primary_key=True),
        sa.Column('dataset_snapshot_id', sa.String(), nullable=False),
        sa.Column('timestamp_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['history_snapshot_id', 'dataset_snapshot_id'], ['history_snapshots.id', 'history_snapshots.dataset_snapshot_id']),
        sa.ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']),
        sa.ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'], ['products.dataset_snapshot_id', 'products.product_id']))
    op.create_table('task_versions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('dataset_snapshot_id', sa.String(), sa.ForeignKey('dataset_snapshots.id'), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('task_id', 'version'),
        sa.CheckConstraint('version > 0', name='positive_task_version'))


def downgrade():
    for table in ('task_versions', 'historical_interactions', 'historical_users', 'history_snapshots',
                  'reviews', 'review_snapshots', 'variants', 'products'):
        op.drop_table(table)
