"""Allow HTTP resource metadata without a local model path; preserve existing records."""
from alembic import op
import sqlalchemy as sa
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('registered_artifacts', 'manifest_path', existing_type=sa.String(), nullable=True)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM registered_artifacts WHERE manifest_path IS NULL')).scalar():
        raise RuntimeError('Remote metadata has no local path; downgrade cannot preserve these records')
    op.alter_column('registered_artifacts', 'manifest_path', existing_type=sa.String(), nullable=False)
