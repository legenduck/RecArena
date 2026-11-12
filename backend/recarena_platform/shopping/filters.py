"""Filter the fixed candidate IDs for presentation without changing their ranks."""
from sqlalchemy import select

from recarena_contracts.http import PriceFilterOptions, SearchFilterOptions
from recarena_platform.db import catalog as catalog


def apply_filters(session, catalog_id, product_ids, filters):
    ratings = {}
    if filters.min_rating is not None:
        ratings = dict(session.execute(select(catalog.Product.product_id, catalog.Product.document['display_rating']).where(
            catalog.Product.dataset_snapshot_id == catalog_id, catalog.Product.product_id.in_(product_ids))).all())
    variants = session.execute(select(catalog.Variant.product_id, catalog.Variant.unit_price_minor, catalog.Variant.currency).where(
        catalog.Variant.dataset_snapshot_id == catalog_id, catalog.Variant.product_id.in_(product_ids),
        catalog.Variant.is_available, catalog.Variant.is_purchasable, catalog.Variant.unit_price_minor.is_not(None))).all()
    currencies = {currency for _, _, currency in variants}
    # These are raw candidate price bounds, not an invented price-band algorithm.
    price = None
    if variants and len(currencies) == 1:
        amounts = [amount for _, amount, _ in variants]
        price = PriceFilterOptions(currency=next(iter(currencies)), min_minor=min(amounts), max_minor=max(amounts))
    eligible = set(product_ids)
    if filters.min_rating is not None:
        eligible &= {pid for pid, rating in ratings.items() if rating is not None and rating >= filters.min_rating}
    if filters.min_price_minor is not None or filters.max_price_minor is not None:
        eligible &= {pid for pid, amount, currency in variants if currency == filters.currency and
            (filters.min_price_minor is None or amount >= filters.min_price_minor) and
            (filters.max_price_minor is None or amount <= filters.max_price_minor)}
    return eligible, SearchFilterOptions(price=price)
