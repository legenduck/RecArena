"""Ranking sources and visible layout ranges are independent contracts."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract, ID, PolicyConfig

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Offset = Annotated[int, Field(strict=True, ge=0)]


class RankingSource(Contract):
    policy: PolicyConfig
    policy_version_id: ID


class GridBlock(Contract):
    id: ID
    source: ID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    component: Literal['grid'] = 'grid'
    offset: Offset = 0
    count: PositiveInt = 20
    columns: Annotated[int, Field(strict=True, ge=1, le=12)] = 4
    visibility: Literal['all_pages', 'first_page'] = 'all_pages'


class PagedRowBlock(Contract):
    id: ID
    source: ID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    component: Literal['paged_row'] = 'paged_row'
    offset: Offset = 0
    total_count: PositiveInt = 20
    visible_count: PositiveInt = 5
    visibility: Literal['all_pages', 'first_page'] = 'first_page'

    @model_validator(mode='after')
    def visible_range(self):
        if self.visible_count > self.total_count:
            raise ValueError('Visible count exceeds section total')
        return self


Block = Annotated[GridBlock | PagedRowBlock, Field(discriminator='component')]


class Layout(Contract):
    main_page_size: PositiveInt = 20
    sidebar_enabled: bool = False
    abandon_enabled: bool = False
    cart_enabled: bool = False
    blocks: Annotated[tuple[Block, ...], Field(min_length=1)]

    @model_validator(mode='after')
    def block_ranges(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError('Duplicate block ID')
        for block in self.blocks:
            if isinstance(block, GridBlock) and block.offset + block.count > self.main_page_size:
                raise ValueError('Grid range exceeds main page size')
        return self


class Presentation(Contract):
    ranking_sources: Annotated[dict[ID, RankingSource], Field(min_length=1)]
    layout: Layout

    @model_validator(mode='after')
    def source_references(self):
        if any(block.source not in self.ranking_sources for block in self.layout.blocks):
            raise ValueError('Block references an unknown ranking source')
        return self

    def validate_ranges(self, candidate_k: int):
        for block in self.layout.blocks:
            if isinstance(block, PagedRowBlock) and block.offset + block.total_count > candidate_k:
                raise ValueError('Section range exceeds candidate K')
        for page in range(1, max(1, (candidate_k + self.layout.main_page_size - 1) // self.layout.main_page_size) + 1):
            ranges = {}
            for block in self.layout.blocks:
                if page > 1 and block.visibility == 'first_page':
                    continue
                start = block.offset + ((page - 1) * self.layout.main_page_size if isinstance(block, GridBlock) else 0)
                end = start + (block.count if isinstance(block, GridBlock) else block.total_count)
                for previous_start, previous_end in ranges.setdefault(block.source, []):
                    if max(start, previous_start) < min(end, previous_end):
                        raise ValueError('Overlapping blocks of the same ranking source')
                ranges[block.source].append((start, end))
        return self


def from_environment(config: dict) -> Presentation:
    """Published historical versions are projected, never rewritten."""
    if 'ranking_sources' in config or 'layout' in config:
        value = {'ranking_sources': config['ranking_sources'], 'layout': config['layout']}
    else:
        size = config['main_page_size']
        value = {'ranking_sources': {'main': {'policy': config['policy'],
            'policy_version_id': config['policy_version_id']}},
            'layout': {'main_page_size': size, 'blocks': [{'id': 'main', 'source': 'main',
                'title': 'Search results', 'component': 'grid', 'count': size}]}}
    if any('policy_id' not in source['policy'] for source in value['ranking_sources'].values()):
        from .legacy_policy import project_sources
        value = {**value, 'ranking_sources': project_sources(config, value['ranking_sources'])}
    presentation = Presentation.model_validate(value)
    conditions = {(source.policy.candidate_scope, source.policy.candidate_limit)
                  for source in presentation.ranking_sources.values()}
    if len(conditions) != 1:
        raise ValueError('Ranking sources must declare the same candidate scope and limit')
    return presentation.validate_ranges(next(iter(conditions))[1])
