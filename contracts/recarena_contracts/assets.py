"""References to an explicitly configured local image collection."""
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .manifest import SHA256
from .models import Contract, ID


class LocalImageReference(Contract):
    asset_id: ID
    source_key: ID
    source_parent_asin: ID
    source_index: Annotated[int, Field(strict=True, ge=0)]
    path: str
    sha256: SHA256 | None = None
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=32 * 1024 * 1024)]
    media_type: Literal['image/jpeg', 'image/png', 'image/webp']
    width: Annotated[int, Field(strict=True, gt=0)] | None = None
    height: Annotated[int, Field(strict=True, gt=0)] | None = None

    @field_validator('path')
    @classmethod
    def relative_path(cls, value):
        path = PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts or '\\' in value or not path.parts:
            raise ValueError('Image reference must stay inside its declared collection')
        return value
