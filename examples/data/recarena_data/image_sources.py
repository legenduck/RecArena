"""Image addresses in the prepared Amazon metadata, in source order."""
from pydantic import TypeAdapter

from recarena_contracts.models import ImageURL

_url = TypeAdapter(ImageURL)


def image_entries(metadata):
    for index, image in enumerate(metadata.get('images') or []):
        url = image.get('large') or image.get('hi_res') or image.get('thumb')
        if url:
            yield index, _url.validate_python(url)
