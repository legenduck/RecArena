"""Versioned research data and HTTP boundary contracts.

Private task data deliberately has no field in ranking or shopping requests.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (AfterValidator, AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field, JsonValue,
                      StringConstraints, TypeAdapter, field_validator, model_validator)
from .text import normalize_query

ID = Annotated[str, StringConstraints(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')]
Currency = Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')]
MinorAmount = Annotated[int, Field(strict=True, ge=0)]
Quantity = Annotated[int, Field(strict=True, ge=1, le=99)]
Score = Annotated[float, Field(allow_inf_nan=False)]
_http_url = TypeAdapter(AnyHttpUrl)


def image_url(value: str) -> str:
    """Validate a browser image address without fetching or rewriting it."""
    _http_url.validate_python(value)
    if value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('Image URL must not contain surrounding whitespace or control characters')
    return value


ImageURL = Annotated[str, Field(pattern=r'^https?://', json_schema_extra={'format': 'uri'}),
                     AfterValidator(image_url)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    @model_validator(mode='after')
    def finite_json(self):
        # Includes values nested in attributes/provenance, not just typed floats.
        json.dumps(self.model_dump(mode='json'), allow_nan=False)
        return self


class Product(Contract):
    dataset_snapshot_id: ID
    product_id: ID
    source_parent_asin: str
    title: Annotated[str, Field(min_length=1)]
    brand: str | None = None
    description: str = ''
    features: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    image_asset_ids: tuple[ID, ...] = ()
    image_urls: tuple[ImageURL, ...] = ()
    currency: Currency
    display_rating: Annotated[float, Field(ge=1, le=5)] | None = None
    display_review_count: Annotated[int, Field(strict=True, ge=0)] = 0
    product_status: Literal['active', 'excluded'] = 'active'
    source_provenance: dict[str, JsonValue]


class Variant(Contract):
    dataset_snapshot_id: ID
    variant_id: ID
    product_id: ID
    source_asin: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    attributes_override: dict[str, JsonValue] = Field(default_factory=dict)
    unit_price_minor: MinorAmount | None = None
    currency: Currency
    image_asset_ids: tuple[ID, ...] = ()
    image_urls: tuple[ImageURL, ...] = ()
    is_available: bool
    is_purchasable: bool
    provenance: dict[str, JsonValue]

    @model_validator(mode='after')
    def purchasable_availability(self):
        if self.is_purchasable and not self.is_available:
            raise ValueError('A purchasable variant requires availability')
        return self


class Review(Contract):
    review_snapshot_id: ID
    review_id: ID
    product_id: ID
    source_asin: str | None = None
    source_user_id: str | None = None
    display_author_alias: str
    rating: Annotated[float, Field(ge=1, le=5)]
    title: str = ''
    body: str
    timestamp_utc: AwareDatetime
    verified_purchase: bool | None = None
    helpful_votes: Annotated[int, Field(strict=True, ge=0)] | None = None
    source_provenance: dict[str, JsonValue]


class ReviewRatingCount(Contract):
    rating: Annotated[float, Field(ge=1, le=5)]
    count: Annotated[int, Field(strict=True, ge=0)]


class PublicReview(Contract):
    review_id: ID
    display_author_alias: str
    rating: Score
    title: str
    body: str
    timestamp_utc: AwareDatetime
    verified_purchase: bool | None
    helpful_votes: int | None

    @classmethod
    def from_review(cls, review: Review):
        return cls.model_validate({k: getattr(review, k) for k in cls.model_fields})


class Interaction(Contract):
    history_snapshot_id: ID
    user_id: ID
    product_id: ID
    source_asin: str | None = None
    rating: Annotated[float, Field(ge=1, le=5)] | None = None
    timestamp_utc: AwareDatetime
    interaction_type: Literal['review_observed'] = 'review_observed'


class PolicyConfig(Contract):
    """A pinned service policy. Its implementation and preparation are provider-owned."""
    family: ID  # Provider-owned label; the platform never dispatches on this value.
    service_id: ID = 'default'
    policy_id: ID
    version: ID
    candidate_scope: ID
    candidate_limit: Annotated[int, Field(strict=True, ge=1)]


class PolicyDefinition(Contract):
    policy: PolicyConfig
    name: Annotated[str, Field(min_length=1)]
    catalog_snapshot_id: ID
    description: str = ''


class Candidate(Contract):
    product_id: ID
    retrieval_rank: Annotated[int, Field(strict=True, ge=1)]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CandidateSet(Contract):
    candidate_set_id: ID
    catalog_snapshot_id: ID
    candidate_scope: ID
    query_raw: str
    query_normalized: Annotated[str, Field(min_length=1, max_length=512)]
    candidates: tuple[Candidate, ...]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len({i.product_id for i in self.candidates}) != len(self.candidates):
            raise ValueError('Duplicate candidate IDs')
        if [i.retrieval_rank for i in self.candidates] != list(range(1, len(self.candidates) + 1)):
            raise ValueError('Candidate retrieval ranks must be consecutive and ordered')
        return self


class UserContext(Contract):
    user_id: ID
    history_snapshot_id: ID


class RankedItem(Contract):
    product_id: ID
    retrieval_rank: Annotated[int, Field(strict=True, ge=1)]
    final_rank: Annotated[int, Field(strict=True, ge=1)]
    final_score: Score | None = None
    score_components: dict[str, Score | None] = Field(default_factory=dict)
    signal_missing_flags: dict[str, bool] = Field(default_factory=dict)


class RankedResult(Contract):
    candidate_set_id: ID
    policy_version_id: ID
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    ranked_items: tuple[RankedItem, ...]
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)

    def validate_candidates(self, candidates: CandidateSet):
        expected = {i.product_id: i.retrieval_rank for i in candidates.candidates}
        if self.candidate_set_id != candidates.candidate_set_id:
            raise ValueError('Candidate set mismatch')
        if len(self.ranked_items) != len(expected) or {i.product_id for i in self.ranked_items} != set(expected):
            raise ValueError('Ranking must preserve every candidate exactly once')
        if [i.final_rank for i in self.ranked_items] != list(range(1, len(expected) + 1)):
            raise ValueError('Invalid final ranks')
        if any(i.retrieval_rank != expected[i.product_id] for i in self.ranked_items):
            raise ValueError('Changed retrieval rank')
        return self


class RunState(str, Enum):
    READY = 'READY'
    RUNNING = 'RUNNING'
    PURCHASED = 'PURCHASED'
    ABANDONED = 'ABANDONED'
    TIMED_OUT = 'TIMED_OUT'
    CANCELLED = 'CANCELLED'
    ERROR = 'ERROR'
    EXPIRED = 'EXPIRED'


RUN_TRANSITIONS = {
    RunState.READY: frozenset({RunState.RUNNING, RunState.EXPIRED, RunState.CANCELLED}),
    RunState.RUNNING: frozenset({RunState.PURCHASED, RunState.ABANDONED, RunState.TIMED_OUT,
                               RunState.CANCELLED, RunState.ERROR}),
}


class EvaluationState(str, Enum):
    NOT_CONFIGURED = 'NOT_CONFIGURED'
    PENDING = 'PENDING'
    COMPLETED = 'COMPLETED'
    INSUFFICIENT_DATA = 'INSUFFICIENT_DATA'
    FAILED = 'FAILED'


class RunLimits(Contract):
    max_quantity: Quantity = 99


class SearchRequest(Contract):
    context_id: ID
    query: Annotated[str, Field(min_length=1, max_length=512)]
    client_request_id: UUID

    @field_validator('query')
    @classmethod
    def valid_query(cls, value):
        normalize_query(value)
        return value


class SelectionRequest(Contract):
    client_request_id: UUID | None = None
    context_id: ID
    variant_id: ID
    quantity: Quantity


class PurchaseRequest(SelectionRequest):
    product_id: ID
    origin_placement_id: ID | None = None


class Constraint(Contract):
    field: str
    op: Literal['eq', 'in', 'contains', 'gte', 'lte', 'between']
    value: JsonValue

    @field_validator('field')
    @classmethod
    def supported_fields(cls, value):
        scalar = {'purchase.quantity', 'purchase.unit_price_minor', 'purchase.total_price_minor'}
        prefixes = ('product.attributes.', 'variant.option_values.', 'variant.attributes_override.')
        if value not in scalar and not any(value.startswith(p) and len(value) > len(p) for p in prefixes):
            raise ValueError('Unsupported evaluation field')
        return value

    @model_validator(mode='after')
    def valid_comparator(self):
        numeric = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
        if self.op in {'gte', 'lte'} and not numeric(self.value):
            raise ValueError('Numeric comparison requires a numeric value, without unit coercion')
        if self.op == 'between':
            if not isinstance(self.value, list) or len(self.value) != 2 or not all(map(numeric, self.value)) or self.value[0] > self.value[1]:
                raise ValueError('between requires ordered numeric bounds')
        if self.op == 'in' and not isinstance(self.value, list):
            raise ValueError('in requires a list')
        return self


class UtilityEntry(Contract):
    product_id: ID
    variant_id: ID
    quantity: Quantity
    utility: Score


class UtilitySpec(Contract):
    kind: Literal['explicit_table'] = 'explicit_table'
    reference_scope: Literal['entire_catalog','specified_eligible_set']
    quantity_domain: Annotated[tuple[Quantity,...],Field(min_length=1)]
    entries: Annotated[tuple[UtilityEntry,...],Field(min_length=1)]
    abandonment_utility: Score | None = None

    @model_validator(mode='after')
    def unique_choices(self):
        if len(set(self.quantity_domain))!=len(self.quantity_domain):
            raise ValueError('Duplicate utility quantities')
        keys={(e.product_id,e.variant_id,e.quantity) for e in self.entries}
        if len(keys)!=len(self.entries) or any(e.quantity not in self.quantity_domain for e in self.entries):
            raise ValueError('Invalid utility choice table')
        return self


class TaskVersion(Contract):
    task_id: ID
    version: Annotated[int, Field(strict=True, ge=1)]
    agent_goal: Annotated[str, Field(min_length=1)]
    private_constraints: tuple[Constraint, ...]
    optional_utility_spec: UtilitySpec | None = None
    catalog_snapshot_id: ID
    validation_status: Literal['DRAFT', 'VALIDATED'] = 'DRAFT'
    provenance: dict[str, JsonValue]


class AgentTask(Contract):
    goal: str


class EventEnvelope(Contract):
    schema_version: Literal['1.0','2.0'] = '1.0'
    recording_method: str | None = None
    occurrence_relative_to_end: Literal['before', 'after', 'unknown', 'not_applicable'] = 'not_applicable'
    event_id: UUID
    run_id: ID | None
    shop_session_id: ID | None = None
    context_id: ID | None = None
    sequence: Annotated[int, Field(strict=True, ge=1)]
    source: Literal['platform_server', 'ranking_server', 'shop_client', 'browser_recorder', 'external_runner', 'operator']
    event_type: ID
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    request_id: str | None = None
    access_path: Literal['url', 'cookie_redirect', 'none'] | None = None
    user_agent: str | None = None
    response_kind: Literal['html', 'data_api', 'control'] | None = None
    measurement_basis: Literal['served', 'observed'] | None = None
    page_instance_id: ID | None = None
    page_instance_kind: Literal['document','legacy_view'] | None = None
    view_id: ID | None = None
    client_sequence: Annotated[int, Field(strict=True, ge=0)] | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    late_received: bool = False
