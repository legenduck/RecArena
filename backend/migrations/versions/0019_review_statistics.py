"""Persist public review distributions without rewriting reviews or products."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('review_statistics',
        sa.Column('review_snapshot_id', sa.String(), primary_key=True),
        sa.Column('product_id', sa.String(), primary_key=True),
        sa.Column('dataset_snapshot_id', sa.String(), nullable=False),
        sa.Column('rating_counts', JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['review_snapshot_id', 'dataset_snapshot_id'],
            ['review_snapshots.id', 'review_snapshots.dataset_snapshot_id']),
        sa.ForeignKeyConstraint(['dataset_snapshot_id', 'product_id'],
            ['products.dataset_snapshot_id', 'products.product_id']),
        sa.CheckConstraint("jsonb_typeof(rating_counts) = 'array'", name='review_rating_counts_array'))
    # One offline aggregation at migration time. Decimal ratings remain exact
    # buckets rather than being rounded into a different star value.
    op.execute("""
        WITH counts AS (
            SELECT review_snapshot_id, dataset_snapshot_id, product_id,
                   (document->>'rating')::numeric AS rating, count(*) AS count
            FROM reviews
            GROUP BY review_snapshot_id, dataset_snapshot_id, product_id,
                     (document->>'rating')::numeric
        ), distributions AS (
            SELECT review_snapshot_id, dataset_snapshot_id, product_id,
                   jsonb_agg(jsonb_build_object('rating', rating, 'count', count)
                             ORDER BY rating DESC) AS rating_counts
            FROM counts
            GROUP BY review_snapshot_id, dataset_snapshot_id, product_id
        )
        INSERT INTO review_statistics
            (review_snapshot_id, product_id, dataset_snapshot_id, rating_counts)
        SELECT s.id, p.product_id, s.dataset_snapshot_id, coalesce(d.rating_counts, '[]'::jsonb)
        FROM review_snapshots s
        JOIN products p ON p.dataset_snapshot_id = s.dataset_snapshot_id
        LEFT JOIN distributions d ON d.review_snapshot_id = s.id
             AND d.dataset_snapshot_id = s.dataset_snapshot_id AND d.product_id = p.product_id
    """)


def downgrade():
    op.drop_table('review_statistics')
