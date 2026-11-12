"""Persist the recording method and logical mutation receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('runs', sa.Column('recording_method', sa.String(), nullable=True))
    op.create_table('shop_action_receipts',
        sa.Column('context_id', sa.String(), sa.ForeignKey('shop_contexts.id'), primary_key=True),
        sa.Column('action', sa.String(), primary_key=True),
        sa.Column('request_key', sa.String(160), primary_key=True),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('response', JSONB(), nullable=False))


def downgrade():
    raise RuntimeError('Downgrade would discard recording metadata and idempotency receipts; restore a verified backup explicitly.')
