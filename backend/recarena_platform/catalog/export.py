"""Export registered product data without selecting fields for any search engine."""
from sqlalchemy import select

from recarena_contracts.catalog import CatalogProducts
from recarena_contracts.models import Product, Variant
from recarena_platform.db import catalog as db


def export_products(session, catalog_id):
    if session.get(db.DatasetSnapshot, catalog_id) is None:
        raise ValueError('Unknown catalog')
    products = session.scalars(select(db.Product).where(
        db.Product.dataset_snapshot_id == catalog_id).order_by(db.Product.product_id))
    variants = session.scalars(select(db.Variant).where(
        db.Variant.dataset_snapshot_id == catalog_id).order_by(db.Variant.variant_id))
    return CatalogProducts(catalog_snapshot_id=catalog_id,
        products=[Product.model_validate(row.document) for row in products],
        variants=[Variant.model_validate(row.document) for row in variants])
