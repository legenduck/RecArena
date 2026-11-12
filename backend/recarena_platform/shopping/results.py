"""Project stored source rankings into requested visible ranges, never rerank."""
from sqlalchemy import select

from recarena_contracts.http import BlockResponse, ProductCard, ResultBlock, ResultFilters, SearchResponse
from recarena_contracts.layout import GridBlock, Presentation, from_environment
from recarena_platform.db import runtime as db
from recarena_platform.catalog.queries import CatalogRepository
from recarena_platform.outcomes import Outcome, rejected
from recarena_platform.events import record_event
from recarena_platform.request_context import image_urls
from recarena_platform.shopping.filters import apply_filters


def snapshot_presentation(snapshot, environment):
    document = snapshot.document
    if 'presentation' in document:
        value = document['presentation']
        if any('policy_id' not in source['policy'] for source in value['ranking_sources'].values()):
            from recarena_contracts.legacy_policy import project_sources
            value = {**value, 'ranking_sources': project_sources(environment.config, value['ranking_sources'])}
        return Presentation.model_validate(value), document['rankings']
    return from_environment(environment.config), {'main': document['ranking']}


def project(session, run, snapshot, main_page, section_pages, request_id, only_block=None, filters=None, *, present=None):
    environment = session.get(db.EnvironmentVersion, run.environment_version_id)
    presentation, rankings = snapshot_presentation(snapshot, environment)
    layout = presentation.layout
    candidate_count = len(next(iter(rankings.values()))['ranked_items'])
    filters = filters or ResultFilters()
    filter_values = filters.model_dump(mode='json', exclude_none=True)
    options = None
    if filter_values and not layout.sidebar_enabled:
        return rejected('FILTERS_DISABLED', 422)
    if layout.sidebar_enabled:
        ids = [item['product_id'] for item in next(iter(rankings.values()))['ranked_items']]
        eligible, options = apply_filters(session, environment.dataset_snapshot_id, ids, filters)
        rankings = {source: {**result, 'ranked_items': [item for item in result['ranked_items'] if item['product_id'] in eligible]}
                    for source, result in rankings.items()}
    result_count = len(next(iter(rankings.values()))['ranked_items'])
    page_count = max(1, (result_count + layout.main_page_size - 1) // layout.main_page_size) if any(
        isinstance(b, GridBlock) and b.visibility == 'all_pages' for b in layout.blocks) else 1
    if main_page < 1 or main_page > page_count:
        return rejected('INVALID_INPUT', 422)
    visible = [b for b in layout.blocks if main_page == 1 or b.visibility == 'all_pages']
    section_ids = {b.id for b in visible}
    if not set(section_pages).issubset(section_ids):
        return rejected('INVALID_INPUT', 422)
    if only_block is not None and only_block not in {b.id for b in visible}:
        return rejected('RESULT_NOT_FOUND', 404)
    # Validate every requested range before writing placements or served events.
    ranges = []
    for block in visible:
        rows = rankings[block.source]['ranked_items']
        if isinstance(block, GridBlock):
            if section_pages.get(block.id, 1) != 1:
                return rejected('INVALID_INPUT', 422)
            section_page, start, size, total = 1, (main_page-1)*layout.main_page_size + block.offset, block.count, block.count
            has_next, columns = False, block.columns
        else:
            section_page = section_pages.get(block.id, 1)
            total = max(0, min(block.total_count, len(rows) - block.offset))
            size = block.visible_count
            if section_page < 1 or section_page > max(1, (total+size-1)//size):
                return rejected('INVALID_INPUT', 422)
            start = block.offset + (section_page-1)*size
            size = min(size, max(0, total-(section_page-1)*size))
            has_next = section_page * block.visible_count < total
            columns = block.visible_count
        ranges.append((block, rows[start:start+size], section_page, has_next, columns))
    # Restrict loading to the ranges being returned, while preserving all range validation above.
    ranges = [value for value in ranges if only_block is None or value[0].id == only_block]
    repo = CatalogRepository(session, environment.dataset_snapshot_id, environment.review_snapshot_id)
    catalog = repo.products_with_variants(item['product_id'] for _, rows, _, _, _ in ranges for item in rows)
    descriptions = {}
    for block, rows, section_page, has_next, columns in ranges:
        for position, item in enumerate(rows, 1):
            description = {'block_id':block.id, 'source_id':block.source, 'source_rank':item['final_rank'],
                           'display_position':position, 'main_page':main_page, 'section_page':section_page}
            if filter_values:
                description['filters'] = filter_values
            descriptions[block.id, position] = description
    existing = list(session.scalars(select(db.Placement).where(
        db.Placement.result_snapshot_id == snapshot.id,
        db.Placement.document.in_(list(descriptions.values()))))) if descriptions else []
    placements, pending = {}, []
    for block, rows, _, _, _ in ranges:
        for position, item in enumerate(rows, 1):
            description = descriptions[block.id, position]
            # Dict equality also preserves JSONB numeric equality for old 3 vs 3.0 filters.
            placement = next((value for value in existing if value.document == description), None)
            if placement is None:
                placement = db.Placement(run_id=run.run_id, context_id=run.id, result_snapshot_id=snapshot.id,
                    dataset_snapshot_id=environment.dataset_snapshot_id, product_id=item['product_id'], document=description)
                pending.append(placement)
            placements[block.id, position] = placement
    if pending:
        session.add_all(pending)
        session.flush()
    blocks = []
    for block, rows, section_page, has_next, columns in ranges:
        cards = []
        for position, item in enumerate(rows, 1):
            placement = placements[block.id, position]
            product, variants = catalog[item['product_id']]
            purchasable = [v for v in variants if v.is_purchasable and v.is_available]
            if not purchasable:
                raise ValueError('Recommendation contains a non-purchasable product')
            prices = [v.unit_price_minor for v in purchasable if v.unit_price_minor is not None]
            images = image_urls(environment.dataset_snapshot_id, remote=product.image_urls,
                local=product.image_asset_ids, placeholder=True)
            cards.append(ProductCard(placement_id=placement.id, product_id=product.product_id,
                title=product.title, image_url=images[0],
                price={'currency':product.currency, 'min_minor':min(prices) if prices else None, 'max_minor':max(prices) if prices else None},
                rating=product.display_rating, review_count=product.display_review_count,
                requires_option_selection=len(variants) != 1,
                default_variant_id=variants[0].variant_id if len(variants) == 1 else None))
        blocks.append(ResultBlock(block_id=block.id, title=block.title, component=block.component,
            columns=columns, section_page=section_page, has_next_page=has_next, items=cards))
        record_event(session, run, 'items_served', {'result_snapshot_id':snapshot.id, 'main_page':main_page,
            'block_id':block.id, 'section_page':section_page, 'placement_ids':[c.placement_id for c in cards],
            'page_type':'results', 'query':snapshot.document['query'], 'sort':'policy_order',
            'items':[{'product_id':c.product_id, 'placement_id':c.placement_id,
                      'rank':row['final_rank'], 'display_position':position}
                     for position,(c,row) in enumerate(zip(cards,rows),1)],
            'filters':filter_values, 'result_count':result_count}, request_id=request_id)
    if only_block is not None:
        response = Outcome(BlockResponse(context_id=run.id, request_id=request_id, result_snapshot_id=snapshot.id,
            main_page=main_page, block=blocks[0]).model_dump(mode='json'))
    else:
        response = Outcome(SearchResponse(context_id=run.id, request_id=request_id, result_snapshot_id=snapshot.id,
            query=snapshot.document['query'], candidate_count=candidate_count, main_page=main_page,
            result_count=result_count, applied_filters=filters, filter_options=options,
            main_page_size=layout.main_page_size, has_next_page=main_page < page_count, blocks=blocks).model_dump(mode='json'))
    # Persist the browser's view alongside this response, using the already loaded layout.
    return present(session, response, presentation) if present else response
