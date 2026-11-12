"""Index the existing product review filter and newest-first pagination order."""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_reviews_snapshot_product_order', 'reviews',
        ['review_snapshot_id', 'product_id', sa.text('timestamp_utc DESC'), 'review_id'])


def downgrade():
    op.drop_index('ix_reviews_snapshot_product_order', table_name='reviews')
