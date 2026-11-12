from collections import Counter
from typing import Literal

from pydantic import AwareDatetime, model_validator

from .models import Contract, ID, Interaction, Product, Review, TaskVersion, Variant
from .manifest import SHA256


class CatalogProducts(Contract):
    """Raw registered products and choices; consumers own any search projection."""
    catalog_snapshot_id: ID
    products: tuple[Product, ...]
    variants: tuple[Variant, ...]

    @model_validator(mode='after')
    def references(self):
        products = {p.product_id for p in self.products}
        if len(products) != len(self.products):
            raise ValueError('Duplicate product IDs')
        if len({v.variant_id for v in self.variants}) != len(self.variants):
            raise ValueError('Duplicate variant IDs')
        if any(p.dataset_snapshot_id != self.catalog_snapshot_id for p in self.products):
            raise ValueError('Product belongs to another catalog')
        if any(v.dataset_snapshot_id != self.catalog_snapshot_id or v.product_id not in products
               for v in self.variants):
            raise ValueError('Variant belongs to another catalog or product')
        return self


class CatalogPackage(Contract):
    """Streaming representation of the same catalog entities, sealed by a manifest."""
    schema_version: Literal['1.0'] = '1.0'
    format: Literal['catalog-jsonl-v1'] = 'catalog-jsonl-v1'
    dataset_snapshot_id: ID
    review_snapshot_id: ID
    history_snapshot_id: ID
    review_cutoff: AwareDatetime | None = None
    history_fingerprint: SHA256
    products_file: Literal['products.jsonl'] = 'products.jsonl'
    variants_file: Literal['variants.jsonl'] = 'variants.jsonl'
    reviews_file: Literal['reviews.jsonl'] = 'reviews.jsonl'
    history_file: Literal['history.jsonl'] = 'history.jsonl'
    tasks_file: Literal['tasks.jsonl'] = 'tasks.jsonl'


class CatalogBundle(Contract):
    schema_version: Literal['1.0'] = '1.0'
    dataset_snapshot_id: ID
    review_snapshot_id: ID
    history_snapshot_id: ID
    review_cutoff: AwareDatetime | None = None
    products: tuple[Product, ...]
    variants: tuple[Variant, ...]
    reviews: tuple[Review, ...]
    history: tuple[Interaction, ...]
    tasks: tuple[TaskVersion, ...] = ()

    @model_validator(mode='after')
    def validate_relations(self):
        products = {p.product_id: p for p in self.products}
        if len(products) != len(self.products):
            raise ValueError('Duplicate product ID')
        if any(p.dataset_snapshot_id != self.dataset_snapshot_id for p in self.products):
            raise ValueError('Product catalog mismatch')
        if len({v.variant_id for v in self.variants}) != len(self.variants):
            raise ValueError('Duplicate variant ID')
        options = set()
        for variant in self.variants:
            if variant.dataset_snapshot_id != self.dataset_snapshot_id or variant.product_id not in products:
                raise ValueError('Variant catalog/product mismatch')
            if variant.currency != products[variant.product_id].currency:
                raise ValueError('Variant currency mismatch')
            key = (variant.product_id, tuple(sorted(variant.option_values.items())))
            if key in options:
                raise ValueError('Ambiguous duplicate option combination')
            options.add(key)
        if len({r.review_id for r in self.reviews}) != len(self.reviews):
            raise ValueError('Duplicate review ID')
        for review in self.reviews:
            if review.review_snapshot_id != self.review_snapshot_id or review.product_id not in products:
                raise ValueError('Review snapshot/product mismatch')
            if self.review_cutoff is not None and review.timestamp_utc > self.review_cutoff:
                raise ValueError('Review exceeds public cutoff')
        by_product = Counter()
        rating_sums = Counter()
        for review in self.reviews:
            by_product[review.product_id] += 1
            rating_sums[review.product_id] += review.rating
        for product in self.products:
            count = by_product[product.product_id]
            expected = rating_sums[product.product_id] / count if count else None
            if product.display_review_count != by_product[product.product_id] or product.display_rating != expected:
                raise ValueError('Displayed ratings/counts must use the public review snapshot')
        pairs = set()
        for interaction in self.history:
            key = (interaction.user_id, interaction.product_id)
            if key in pairs:
                raise ValueError('History must contain deduplicated user-parent-product pairs')
            pairs.add(key)
            if interaction.history_snapshot_id != self.history_snapshot_id or interaction.product_id not in products:
                raise ValueError('History snapshot/product mismatch')
        for task in self.tasks:
            if task.catalog_snapshot_id != self.dataset_snapshot_id:
                raise ValueError('Task catalog mismatch')
        if len({(t.task_id, t.version) for t in self.tasks}) != len(self.tasks):
            raise ValueError('Duplicate task version')
        return self
