"""Client events have an allowlisted payload and a server-owned source."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator,field_validator

from .models import Contract, ID

RECORDING_METHOD = 'rendered_list'


class PagePayload(Contract):
    page_type: Literal['home','results','detail','cart','terminal']
    result_snapshot_id: ID | None = None
    product_id: ID | None = None


class PlacementPayload(Contract):
    result_snapshot_id: ID
    block_id: ID
    placement_id: ID
    list_presentation_id: UUID | None = None


class PresentedItem(Contract):
    product_id: ID
    placement_id: ID


class ListPresentationPayload(Contract):
    result_snapshot_id: ID
    block_id: ID
    list_presentation_id: UUID
    main_page: Annotated[int, Field(strict=True, ge=1)]
    section_page: Annotated[int, Field(strict=True, ge=1)]
    items: tuple[PresentedItem, ...]

    @model_validator(mode='after')
    def unique_positions(self):
        if len({i.placement_id for i in self.items}) != len(self.items):
            raise ValueError('A presentation must not repeat a placement')
        return self


class ImpressionPayload(PlacementPayload):
    visible_ratio: Annotated[float, Field(strict=True,ge=.5,le=1)]
    visible_duration_ms: Annotated[float, Field(strict=True,ge=1000)]
    document_visible: Literal[True]

    @field_validator('document_visible',mode='before')
    @classmethod
    def actually_boolean_true(cls,value):
        if value is not True:
            raise ValueError('A visible document must be reported as boolean true')
        return value


class ResultPagePayload(Contract):
    result_snapshot_id: ID
    main_page: Annotated[int,Field(strict=True,ge=1)]


class SectionPagePayload(ResultPagePayload):
    block_id: ID
    section_page: Annotated[int,Field(strict=True,ge=1)]


class ScrollPayload(Contract):
    scroll_x: Annotated[float,Field(strict=True,ge=0)]
    scroll_y: Annotated[float,Field(strict=True,ge=0)]
    viewport_width: Annotated[int,Field(strict=True,ge=1)]
    viewport_height: Annotated[int,Field(strict=True,ge=1)]


class ReviewPayload(Contract):
    product_id: ID


class ReviewDisplayPayload(ReviewPayload):
    offset: Annotated[int, Field(strict=True, ge=0)]
    review_ids: Annotated[tuple[ID, ...], Field(max_length=50)]


PAYLOADS = {'page_viewed':PagePayload,'card_rendered':PlacementPayload,'card_impression':ImpressionPayload,
    'item_list_rendered':ListPresentationPayload, 'reviews_rendered':ReviewDisplayPayload,
    'product_clicked':PlacementPayload,'result_page_changed':ResultPagePayload,'section_page_changed':SectionPagePayload,
    'scroll_sampled':ScrollPayload,'review_section_entered':ReviewPayload,'review_expanded':ReviewPayload}


class ClientEvent(Contract):
    recording_method: Literal['rendered_list'] | None = None
    context_id: ID
    event_id: UUID
    event_type: Literal['page_viewed','card_rendered','card_impression','product_clicked','result_page_changed',
                        'section_page_changed','scroll_sampled','review_section_entered','review_expanded','item_list_rendered','reviews_rendered']
    occurred_at: AwareDatetime
    page_instance_id: UUID
    view_id: UUID | None = None
    client_sequence: Annotated[int,Field(strict=True,ge=0)]
    payload: dict[str,JsonValue]

    @model_validator(mode='after')
    def allowed_payload(self):
        PAYLOADS[self.event_type].model_validate(self.payload)
        if self.event_type in {'item_list_rendered','reviews_rendered'} and self.recording_method != RECORDING_METHOD:
            raise ValueError('Rendered events require their recording method')
        if self.recording_method == RECORDING_METHOD and self.event_type == 'product_clicked' and not self.payload.get('list_presentation_id'):
            raise ValueError('Product selections require their originating presentation')
        return self


class ClientEventsBatch(Contract):
    events: Annotated[tuple[ClientEvent,...],Field(min_length=1,max_length=100)]
