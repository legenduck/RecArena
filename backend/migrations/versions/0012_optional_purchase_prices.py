"""Allow explicit unknown prices without fabricating purchase amounts."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('variant_verified_purchase', 'variants', type_='check')
    op.create_check_constraint('variant_verified_purchase', 'variants', 'NOT is_purchasable OR is_available')
    op.drop_constraint('purchase_amount_valid', 'purchases', type_='check')
    op.alter_column('purchases', 'unit_price_minor', existing_type=sa.BigInteger(), nullable=True)
    op.alter_column('purchases', 'total_price_minor', existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint('purchase_amount_valid', 'purchases',
        '(unit_price_minor IS NULL AND total_price_minor IS NULL) OR '
        '(unit_price_minor IS NOT NULL AND total_price_minor IS NOT NULL AND unit_price_minor >= 0 '
        'AND total_price_minor = unit_price_minor * quantity)')


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM purchases WHERE unit_price_minor IS NULL OR total_price_minor IS NULL) '
        'OR EXISTS (SELECT 1 FROM variants WHERE is_purchasable AND unit_price_minor IS NULL)')):
        raise RuntimeError('Cannot restore mandatory prices while unpriced purchases or purchasable variants exist; preserve the records.')
    op.drop_constraint('purchase_amount_valid', 'purchases', type_='check')
    op.alter_column('purchases', 'unit_price_minor', existing_type=sa.BigInteger(), nullable=False)
    op.alter_column('purchases', 'total_price_minor', existing_type=sa.BigInteger(), nullable=False)
    op.create_check_constraint('purchase_amount_valid', 'purchases', 'unit_price_minor >= 0 AND total_price_minor = unit_price_minor * quantity')
    op.drop_constraint('variant_verified_purchase', 'variants', type_='check')
    op.create_check_constraint('variant_verified_purchase', 'variants', 'NOT is_purchasable OR (is_available AND unit_price_minor IS NOT NULL)')
