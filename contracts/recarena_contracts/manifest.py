from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from .models import Contract, ID

SHA256 = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class SourceFile(Contract):
    name: str
    sha256: SHA256


class ArtifactFile(Contract):
    path: str
    sha256: SHA256
    size_bytes: Annotated[int, Field(strict=True, ge=0)]

    @field_validator('path')
    @classmethod
    def relative_file(cls, value):
        path = PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts or '\\' in value or not path.parts:
            raise ValueError('Artifact file path must be relative and contained')
        return value


class ArtifactManifest(Contract):
    schema_version: Literal['1.0'] = '1.0'
    artifact_id: ID
    # The consuming module owns its formats; the platform need not enumerate
    # every optional recommendation provider's artifact types.
    artifact_type: ID
    created_at: AwareDatetime
    source_files: tuple[SourceFile, ...]
    config_hash: SHA256
    code_commit: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{40}$')] | None = None
    code_dirty: bool | None = None
    source_tree_sha256: SHA256 | None = None
    parent_artifact_ids: tuple[ID, ...]
    counts: dict[str, Annotated[int, Field(strict=True, ge=0)]]
    files: tuple[ArtifactFile, ...]
    warnings: tuple[str, ...]

    @model_validator(mode='after')
    def unique_paths(self):
        if len({f.path for f in self.files}) != len(self.files):
            raise ValueError('Duplicate artifact file paths')
        return self
