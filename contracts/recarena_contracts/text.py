import unicodedata


def normalize_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError('Query must be text')
    value = ' '.join(unicodedata.normalize('NFKC', query).split())
    value = ''.join(c for c in value if not unicodedata.category(c).startswith('C'))
    value = ' '.join(value.split())
    if not value or len(value) > 512:
        raise ValueError('Query length must be between 1 and 512 characters')
    return value
