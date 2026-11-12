"""Rename legacy database helper functions while preserving their trigger bindings."""
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    # Applied migrations retain their historical names. ALTER preserves OIDs,
    # trigger ownership and every data row, including immutable records.
    op.execute('ALTER FUNCTION recagent_immutable_update() RENAME TO recarena_immutable_update')
    op.execute('ALTER FUNCTION recagent_fixed_record_update() RENAME TO recarena_fixed_record_update')


def downgrade():
    op.execute('ALTER FUNCTION recarena_fixed_record_update() RENAME TO recagent_fixed_record_update')
    op.execute('ALTER FUNCTION recarena_immutable_update() RENAME TO recagent_immutable_update')
