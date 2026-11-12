"""First durable catalog artifact registry; expanded by M1 migrations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dataset_snapshots',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('manifest', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()))


def downgrade():
    op.drop_table('dataset_snapshots')
