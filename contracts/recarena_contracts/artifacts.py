"""File-based, immutable artifacts shared between isolated Python environments."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .manifest import ArtifactManifest
from .source_provenance import provenance


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def make_manifest(directory: Path, artifact_type: str, config: dict, *,
                  sources: list[Path] | None = None, parents: list[str] | None = None,
                  counts: dict | None = None, warnings: list[str] | None = None,
                  artifact_id: str | None = None, source_scope: str = "platform") -> dict:
    manifest = {
        'schema_version': '1.0', 'artifact_id': artifact_id or str(uuid4()), 'artifact_type': artifact_type,
        'created_at': datetime.now(timezone.utc).isoformat(), **provenance(source_scope),
        'source_files': [{'name': p.name, 'sha256': digest(p)} for p in sources or []],
        'config_hash': canonical_hash(config), 'parent_artifact_ids': parents or [],
        'counts': counts or {}, 'warnings': warnings or [],
        'files': [{'path': str(p.relative_to(directory)), 'sha256': digest(p),
                   'size_bytes': p.stat().st_size}
                  for p in sorted(directory.rglob('*')) if p.is_file() and p != directory / 'manifest.json'],
    }
    ArtifactManifest.model_validate(manifest)
    write_json(directory / 'manifest.json', manifest)
    return manifest


def verify_manifest(path: Path) -> dict:
    manifest = ArtifactManifest.model_validate_json(path.read_text()).model_dump(mode='json')
    root = path.parent.resolve()
    seen = set()
    for entry in manifest['files']:
        file = (root / entry['path']).resolve()
        if not file.is_relative_to(root) or file == path.resolve() or file in seen:
            raise ValueError('Invalid artifact file path')
        seen.add(file)
        if file.stat().st_size != entry['size_bytes'] or digest(file) != entry['sha256']:
            raise ValueError(f'Artifact checksum mismatch: {entry["path"]}')
    actual = {p.resolve() for p in root.rglob('*') if p.is_file() and p != path.resolve()}
    if actual != seen:
        raise ValueError('Artifact contains unmanifested files')
    return manifest
