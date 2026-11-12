"""Confirmed line items and totals; unknown prices and currencies stay distinct."""
from .models import Contract, ID, Quantity, Currency, MinorAmount


class PurchaseItem(Contract):
    product_id: ID
    variant_id: ID
    title: str
    selected_options: dict[str, str]
    quantity: Quantity
    unit_price_minor: MinorAmount | None
    total_price_minor: MinorAmount | None
    currency: Currency
    origin_placement_id: ID | None = None


def item_totals(items):
    amounts = {}
    quantity = 0
    for item in items:
        currency, value = item['currency'], item['total_price_minor']
        quantity += item['quantity']
        previous = amounts.get(currency, 0)
        amounts[currency] = None if previous is None or value is None else previous + value
    currency = next(iter(amounts)) if len(amounts) == 1 else None
    return {'total_quantity': quantity, 'totals_by_currency': amounts, 'currency': currency,
            'total_price_minor': amounts[currency] if currency else (0 if not items else None)}
