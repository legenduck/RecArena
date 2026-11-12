"""Request-local transport facts; never use ambient context to select a Run."""
from contextvars import ContextVar

request_context = ContextVar('shopping_request', default={})


def event_metadata(event_type):
    context = request_context.get()
    fields = {key: context[key] for key in ('access_path', 'user_agent', 'response_kind') if key in context}
    if event_type in {'items_served', 'product_detail_served', 'reviews_served', 'cart_served'}:
        fields['measurement_basis'] = 'served'
    elif event_type in {'item_list_rendered', 'reviews_rendered', 'page_viewed'}:
        fields['measurement_basis'] = 'observed'
    return fields


def asset_url(catalog_id, asset_id):
    # The immutable URL session determines the catalog on the server.
    return f"{request_context.get().get('session_prefix', '')}/assets/{asset_id}"


def image_urls(catalog_id, *, remote=(), local=(), placeholder=False):
    """Use supplied URLs by default; explicit local assets select self hosting."""
    if local:
        return [asset_url(catalog_id, asset_id) for asset_id in local]
    if remote:
        return list(remote)
    return ['/product-placeholder.svg'] if placeholder else []
