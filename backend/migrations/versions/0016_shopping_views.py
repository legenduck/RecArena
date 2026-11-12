"""Persist opaque browser views without rewriting historical research records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('shopping_views',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('context_id', sa.String(), sa.ForeignKey('shop_contexts.id'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_shopping_views_context_id', 'shopping_views', ['context_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM shopping_views')).scalar():
        raise RuntimeError('Shopping views exist; downgrade would break saved page and event references')
    op.drop_table('shopping_views')
