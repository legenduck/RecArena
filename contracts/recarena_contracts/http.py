"""Explicit public/control/internal DTOs. No private task data in ranker/shop."""
from typing import Annotated, Literal
from uuid import UUID

from .commerce import PurchaseItem
from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator
from .text import normalize_query
from .layout import Presentation

from .models import (Contract, ID, CandidateSet, Currency, MinorAmount, PolicyConfig,
                     PublicReview, ReviewRatingCount, Quantity, RunLimits, RunState, RankedResult, UserContext)


class RunCreate(Contract):
    environment_version_id: ID
    user_id: ID
    task_version_id: ID | None = None
    limits: RunLimits = Field(default_factory=RunLimits)
    run_kind: Literal['research', 'preview'] = 'research'


class SessionCreate(Contract):
    user_id: ID
    policy: ID
    agent: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    task_id: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    client_run_id: Annotated[str, Field(min_length=1, max_length=160)] | None = None


class SessionEnd(Contract):
    reason: Literal['researcher_end', 'agent_stop', 'budget_exhausted', 'runner_error', 'administrator_cancel'] = 'researcher_end'


class ContextRequest(Contract):
    context_id: ID


class PreparedRunStart(Contract):
    shop_session_id: ID


class SiteSettingsRequest(Contract):
    default_environment_id: ID | None
    policies: dict[ID, ID]


class RecommendationRequest(Contract):
    query: Annotated[str, Field(min_length=1, max_length=512)]
    catalog_snapshot_id: ID
    user: UserContext
    policy: PolicyConfig
    policy_version_id: ID
    candidates: CandidateSet | None = None

    @field_validator('query')
    @classmethod
    def valid_query(cls, value):
        normalize_query(value)
        return value


class RecommendationResponse(Contract):
    policy: PolicyConfig
    candidates: CandidateSet
    ranking: RankedResult


class PolicyValidationRequest(Contract):
    catalog_snapshot_id: ID
    user: UserContext
    policy: PolicyConfig
    strict_user: bool = True


class ControlPolicyRequest(Contract):
    environment_version_id: ID
    user_id: ID
    policy: PolicyConfig | None = None
    source_id: ID = 'main'


class EnvironmentBindings(Contract):
    catalog_snapshot_id: ID
    review_snapshot_id: ID
    history_snapshot_id: ID


class EnvironmentDraftRequest(Contract):
    base_environment_id: ID | None = None
    presentation: Presentation | None = None
    bindings: EnvironmentBindings | None = None


class EnvironmentLayoutRequest(Contract):
    presentation: Presentation


class EnvironmentValidationRequest(Contract):
    user_id: ID


class PolicyDiagnosticRequest(ControlPolicyRequest):
    query: Annotated[str, Field(min_length=1, max_length=512)]

    @field_validator('query')
    @classmethod
    def valid_query(cls, value):
        normalize_query(value)
        return value


class Price(Contract):
    currency: Currency
    min_minor: MinorAmount | None
    max_minor: MinorAmount | None


class ProductCard(Contract):
    placement_id: ID
    product_id: ID
    title: str
    image_url: str
    price: Price
    rating: float | None
    review_count: int
    requires_option_selection: bool
    default_variant_id: ID | None


class ResultBlock(Contract):
    block_id: ID
    title: str
    component: Literal['grid', 'paged_row']
    items: tuple[ProductCard, ...]
    columns: int
    section_page: int
    has_next_page: bool


class ResultFilters(Contract):
    min_rating: Literal[3, 4, 5] | None = None
    min_price_minor: MinorAmount | None = None
    max_price_minor: MinorAmount | None = None
    currency: Currency | None = None

    @model_validator(mode='after')
    def price_range(self):
        price_active = self.min_price_minor is not None or self.max_price_minor is not None
        if price_active and self.currency is None:
            raise ValueError('Price filters require a currency')
        if self.currency is not None and not price_active:
            raise ValueError('Currency requires an active price range')
        if self.min_price_minor is not None and self.max_price_minor is not None and self.min_price_minor > self.max_price_minor:
            raise ValueError('Minimum price exceeds maximum price')
        return self


class PriceBand(Contract):
    min_minor: MinorAmount | None = None
    max_minor: MinorAmount | None = None

    @model_validator(mode='after')
    def bounds(self):
        if self.min_minor is None and self.max_minor is None:
            raise ValueError('A price band needs a bound')
        if self.min_minor is not None and self.max_minor is not None and self.min_minor > self.max_minor:
            raise ValueError('Invalid price band')
        return self


class PriceFilterOptions(Contract):
    currency: Currency
    min_minor: MinorAmount
    max_minor: MinorAmount
    max_open_ended: bool = False
    # Boundaries are supplied by the selected rule; no guessed five-band rule.
    bands: tuple[PriceBand, ...] = ()

    @model_validator(mode='after')
    def bounds(self):
        if self.min_minor > self.max_minor or len(self.bands) not in (0, 5):
            raise ValueError('Price options require ordered bounds and five bands when configured')
        return self


class SearchFilterOptions(Contract):
    price: PriceFilterOptions | None = None


class BlockResponse(Contract):
    context_id: ID
    request_id: UUID
    result_snapshot_id: ID
    main_page: int
    block: ResultBlock


class SearchResponse(Contract):
    context_id: ID
    request_id: UUID
    result_snapshot_id: ID
    query: str
    candidate_count: int
    result_count: int
    applied_filters: ResultFilters = Field(default_factory=ResultFilters)
    filter_options: SearchFilterOptions | None = None
    main_page: int
    main_page_size: int
    has_next_page: bool
    blocks: tuple[ResultBlock, ...]


class PublicVariant(Contract):
    variant_id: ID
    option_values: dict[str, str]
    attributes_override: dict[str, JsonValue]
    unit_price_minor: MinorAmount | None
    currency: Currency
    image_urls: tuple[str, ...]
    is_available: bool
    is_purchasable: bool


class PublicSelection(Contract):
    variant_id: ID
    quantity: Quantity


class ProductDetail(Contract):
    context_id: ID
    request_id: UUID
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


class ReviewsResponse(Contract):
    context_id: ID
    request_id: UUID
    reviews: tuple[PublicReview, ...]
    has_more: bool


class PurchaseResponse(Contract):
    request_id: UUID
    id: ID
    run_id: ID | None
    context_id: ID
    product_id: ID | None
    variant_id: ID | None
    selected_options: dict[str, str] | None
    quantity: Quantity | None
    unit_price_minor: MinorAmount | None
    total_price_minor: MinorAmount | None
    currency: Currency | None
    origin_placement_id: ID | None
    purchased_at: AwareDatetime

    items: tuple[PurchaseItem, ...]
    total_quantity: int
    totals_by_currency: dict[str, int | None]


class ShopSessionResponse(Contract):
    request_id: UUID
    shop_session_id: ID
    context_id: ID
    run_id: ID | None
    state: RunState | Literal['GENERAL']
    experiment_active: bool
    environment_ready: bool
    max_quantity: Quantity
    purchase: PurchaseResponse | None
