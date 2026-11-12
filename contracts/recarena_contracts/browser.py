"""Allowlisted shopping transport. Research identifiers never cross this boundary."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from .models import Contract, ID, Quantity, Currency, MinorAmount, PublicReview, ReviewRatingCount
from .http import Price, PublicVariant, PublicSelection, ResultFilters, SearchFilterOptions


class BrowserReceiptItem(Contract):
    product_id: ID
    variant_id: ID
    title: str
    selected_options: dict[str, str]
    quantity: Quantity
    unit_price_minor: MinorAmount | None
    total_price_minor: MinorAmount | None
    currency: Currency


class BrowserReceipt(Contract):
    items: tuple[BrowserReceiptItem, ...]
    total_quantity: int
    totals_by_currency: dict[str, int | None]
    total_price_minor: MinorAmount | None
    currency: Currency | None
    # Preserve the single-item receipt fields for existing clients.
    product_id: ID | None
    selected_options: dict[str, str] | None
    quantity: Quantity | None
    unit_price_minor: MinorAmount | None


class BrowserCartItem(BrowserReceiptItem):
    item_id: UUID
    image_url: str
    # Old idempotent cart responses did not record availability. Keep it unknown.
    is_available: bool | None = None
    is_purchasable: bool | None = None


class BrowserCart(Contract):
    viewId: UUID
    items: tuple[BrowserCartItem, ...]
    total_quantity: int
    totals_by_currency: dict[str, int | None]


class BrowserSession(Contract):
    viewId: UUID
    status: Literal['active', 'purchased', 'abandoned', 'ended']
    max_quantity: Quantity
    show_abandon: bool
    show_cart: bool
    cart_quantity: int
    purchase: BrowserReceipt | None


class BrowserCard(Contract):
    item_key: str
    product_id: ID
    title: str
    image_url: str
    price: Price
    rating: float | None
    review_count: int
    requires_option_selection: bool
    default_variant_id: ID | None


class BrowserBlock(Contract):
    viewId: UUID
    block_id: str
    title: str
    component: Literal['grid', 'paged_row']
    items: tuple[BrowserCard, ...]
    columns: int
    section_page: int
    has_next_page: bool


class BrowserResults(Contract):
    viewId: UUID
    query: str
    result_count: int
    applied_filters: ResultFilters
    filter_options: SearchFilterOptions | None
    main_page: int
    main_page_size: int
    has_next_page: bool
    blocks: tuple[BrowserBlock, ...]


class BrowserBlockResponse(Contract):
    viewId: UUID
    main_page: int
    block: BrowserBlock


class BrowserProduct(Contract):
    viewId: UUID
    product_id: ID
    title: str
    brand: str | None
    description: str
    features: tuple[str, ...]
    categories: tuple[str, ...]
    attributes: dict[str, JsonValue]
    image_urls: tuple[str, ...]
    rating: float | None
    review_count: int
    rating_distribution: tuple[ReviewRatingCount, ...] | None = None
    variants: tuple[PublicVariant, ...]
    selection: PublicSelection | None


class BrowserReviews(Contract):
    viewId: UUID
    reviews: tuple[PublicReview, ...]
    has_more: bool


class ViewRequest(Contract):
    viewId: UUID


class BrowserSearch(ViewRequest):
    query: Annotated[str, Field(min_length=1, max_length=512)]
    requestKey: UUID


class BrowserSelection(ViewRequest):
    requestKey: UUID
    variant_id: ID
    quantity: Quantity


class BrowserCartQuantity(ViewRequest):
    quantity: Quantity


class BrowserPurchase(ViewRequest):
    product_id: ID
    variant_id: ID
    quantity: Quantity
    item_key: str | None = None


class BrowserEvent(ViewRequest):
    documentId: UUID | None = None
    event_id: UUID
    event_type: Literal['page_viewed', 'item_list_rendered', 'product_clicked',
        'result_page_changed', 'section_page_changed', 'scroll_sampled',
        'reviews_rendered', 'review_section_entered', 'review_expanded']
    occurred_at: AwareDatetime
    client_sequence: Annotated[int, Field(strict=True, ge=0)]
    payload: dict[str, JsonValue]


class BrowserEvents(Contract):
    events: Annotated[tuple[BrowserEvent, ...], Field(min_length=1, max_length=100)]
