"""Resolve catalog image references for streaming, without per-request hashing."""
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import stat

from recarena_contracts.artifacts import verify_manifest
from recarena_contracts.assets import LocalImageReference

MAX_IMAGE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LocalAsset:
    root: Path
    relative_path: str
    sha256: str | None
    size_bytes: int
    media_type: str

    def resolve_file(self):
        path = (self.root / self.relative_path).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError('Image path escapes declared root')
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_IMAGE_BYTES:
            raise ValueError('Image must be a regular file within the serving size limit')
        return path, file_stat


def load_asset_config(filename):
    assets = {}
    if not filename:
        return assets
    configuration = json.loads(Path(filename).read_text())
    roots = {key: Path(value).resolve(strict=True) for key, value in configuration.get('roots', {}).items()}
    if any(not root.is_dir() for root in roots.values()):
        raise ValueError('An image collection root must be a local directory')

    def register(catalog_id, asset_id, asset):
        key = (catalog_id, asset_id)
        if key in assets:
            raise ValueError('Duplicate asset ID')
        assets[key] = asset

    for filename in configuration['manifests']:
        path = Path(filename).resolve()
        manifest = verify_manifest(path)
        if manifest['artifact_type'] != 'assets' or len(manifest['parent_artifact_ids']) != 1:
            raise ValueError('Invalid asset manifest')
        catalog_id = manifest['parent_artifact_ids'][0]
        for entry in manifest['files']:
            relative = Path(entry['path'])
            if entry['path'] == 'asset_index.jsonl':
                count = 0
                with (path.parent / relative).open() as stream:
                    for line in stream:
                        reference = LocalImageReference.model_validate_json(line)
                        if reference.source_key not in roots:
                            raise ValueError('Image reference has no configured local root')
                        register(catalog_id, reference.asset_id, LocalAsset(roots[reference.source_key],
                            reference.path, reference.sha256, reference.size_bytes, reference.media_type))
                        count += 1
                if count != manifest['counts'].get('referenced_images'):
                    raise ValueError('Local image reference count mismatch')
            elif relative.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.svg'}:
                if entry['size_bytes'] > MAX_IMAGE_BYTES:
                    raise ValueError('Image exceeds serving size limit')
                register(catalog_id, relative.stem, LocalAsset(path.parent, entry['path'], entry['sha256'],
                    entry['size_bytes'], mimetypes.guess_type(relative.name)[0] or 'application/octet-stream'))
    return assets
