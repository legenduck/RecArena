"""Lossless storage of review text that PostgreSQL JSONB cannot represent directly.

The NUL character is valid in JSON strings but unsupported by PostgreSQL text.
Only affected fields are JSON-encoded once more for storage, then decoded before
the existing public review projection. Original prepared files stay unchanged.
"""
import json

from recarena_contracts.models import Review

MARKER = '_pg_json_text_v1'


def review_document(review: Review):
    document = review.model_dump(mode='json')
    encoded = [key for key, value in document.items() if isinstance(value, str) and '\0' in value]
    for key in encoded:
        document[key] = json.dumps(document[key], ensure_ascii=True)
    if encoded:
        document[MARKER] = encoded
    return document


def read_review(document):
    values = dict(document)
    for key in values.pop(MARKER, []):
        if key not in Review.model_fields or not isinstance(values.get(key), str):
            raise ValueError('Invalid encoded review field')
        decoded = json.loads(values[key])
        if not isinstance(decoded, str):
            raise ValueError('Encoded review text must decode to a string')
        values[key] = decoded
    return Review.model_validate(values)
