"""Optional session carts and one final purchase containing multiple items."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('carts',
        sa.Column('context_id', sa.String(), sa.ForeignKey('shop_contexts.id'), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('items', JSONB(), nullable=False, server_default='[]'),
        sa.CheckConstraint('version >= 0', name='cart_version_valid'),
        sa.CheckConstraint("jsonb_typeof(items) = 'array'", name='cart_items_array'))
    op.add_column('purchases', sa.Column('items', JSONB(), nullable=True))
    for name, kind in [('product_id', sa.String()), ('variant_id', sa.String()),
                       ('selected_options', JSONB()), ('quantity', sa.Integer()), ('currency', sa.String(3))]:
        op.alter_column('purchases', name, existing_type=kind, nullable=True)
    op.drop_constraint('purchase_amount_valid', 'purchases', type_='check')
    op.create_check_constraint('purchase_amount_valid', 'purchases',
        "(items IS NOT NULL AND jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 1 "
            "AND product_id IS NULL AND variant_id IS NULL AND quantity IS NULL AND unit_price_minor IS NULL "
            "AND (total_price_minor IS NULL OR (total_price_minor >= 0 AND currency IS NOT NULL))) OR "
        '(unit_price_minor IS NULL AND total_price_minor IS NULL) OR '
        '(unit_price_minor IS NOT NULL AND total_price_minor IS NOT NULL AND unit_price_minor >= 0 '
        'AND total_price_minor = unit_price_minor * quantity)')
    op.create_check_constraint('purchase_shape_valid', 'purchases', "(product_id IS NOT NULL AND variant_id IS NOT NULL AND quantity IS NOT NULL AND currency IS NOT NULL AND jsonb_typeof(selected_options) = 'object' AND (items IS NULL OR (jsonb_typeof(items) = 'array' AND jsonb_array_length(items) = 1))) OR (product_id IS NULL AND variant_id IS NULL AND quantity IS NULL AND unit_price_minor IS NULL AND items IS NOT NULL AND jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 1)")
    # Legacy rows are not rewritten or relabelled as cart purchases.


def downgrade():
    raise RuntimeError('Cart/purchase records must be preserved; restore a verified backup explicitly.')
