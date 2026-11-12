from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.models import Product, Variant, Review, PublicReview
from recarena_platform.db import catalog as db
from recarena_platform.catalog.reviews import read_review


class CatalogRepository:
    def __init__(self, session: Session, catalog_id: str, review_id: str):
        self.session = session
        self.catalog_id = catalog_id
        snapshot = session.get(db.ReviewSnapshot, review_id)
        if snapshot is None or snapshot.dataset_snapshot_id != catalog_id:
            raise ValueError('ARTIFACT_MISMATCH: review snapshot and catalog')
        self.review_id = review_id

    def product(self, product_id: str) -> Product:
        record = self.session.get(db.Product, (self.catalog_id, product_id))
        if record is None:
            raise KeyError(product_id)
        return Product.model_validate(record.document)

    def variants(self, product_id: str) -> list[Variant]:
        records = self.session.scalars(select(db.Variant).where(
            db.Variant.dataset_snapshot_id == self.catalog_id,
            db.Variant.product_id == product_id).order_by(db.Variant.variant_id))
        return [Variant.model_validate(r.document) for r in records]

    def products_with_variants(self, product_ids):
        """Load just the displayed products and their ordered options in two queries."""
        identifiers = set(product_ids)
        if not identifiers:
            return {}
        products = {record.product_id: Product.model_validate(record.document)
            for record in self.session.scalars(select(db.Product).where(
                db.Product.dataset_snapshot_id == self.catalog_id,
                db.Product.product_id.in_(identifiers)))}
        missing = identifiers - products.keys()
        if missing:
            raise KeyError(next(iter(missing)))
        variants = {identifier: [] for identifier in identifiers}
        for record in self.session.scalars(select(db.Variant).where(
                db.Variant.dataset_snapshot_id == self.catalog_id,
                db.Variant.product_id.in_(identifiers))
                .order_by(db.Variant.product_id, db.Variant.variant_id)):
            variants[record.product_id].append(Variant.model_validate(record.document))
        return {identifier: (product, variants[identifier]) for identifier, product in products.items()}

    def rating_distribution(self, product_id: str):
        record = self.session.get(db.ReviewStatistics, (self.review_id, product_id))
        return record.rating_counts if record is not None else None

    def reviews(self, product_id: str, offset=0, limit=10) -> list[PublicReview]:
        if offset < 0 or limit < 1 or limit > 100:
            raise ValueError('Invalid review range')
        records = self.session.scalars(select(db.Review).where(
            db.Review.review_snapshot_id == self.review_id,
            db.Review.dataset_snapshot_id == self.catalog_id,
            db.Review.product_id == product_id).order_by(db.Review.timestamp_utc.desc(), db.Review.review_id.asc())
            .offset(offset).limit(limit))
        return [PublicReview.from_review(read_review(r.document)) for r in records]
