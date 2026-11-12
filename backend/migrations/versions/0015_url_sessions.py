"""URL session credentials and control-request retries; legacy rows stay unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('shop_sessions', sa.Column('entry_id', sa.String(43), nullable=True))
    op.add_column('shop_sessions', sa.Column('issuance_key', sa.String(160), nullable=True))
    op.create_unique_constraint('session_entry_id_unique', 'shop_sessions', ['entry_id'])
    op.create_unique_constraint('session_issuance_key_unique', 'shop_sessions', ['issuance_key'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM shop_sessions WHERE entry_id IS NOT NULL')).scalar():
        raise RuntimeError('URL sessions exist; downgrade would lose their entry credentials')
    op.drop_constraint('session_issuance_key_unique', 'shop_sessions')
    op.drop_constraint('session_entry_id_unique', 'shop_sessions')
    op.drop_column('shop_sessions', 'issuance_key')
    op.drop_column('shop_sessions', 'entry_id')
