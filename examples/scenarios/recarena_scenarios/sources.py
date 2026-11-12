"""Resolve the common prepared-data contract; never recompute its time split."""
from dataclasses import dataclass
from pathlib import Path

from .artifacts import read_json, file_hash


@dataclass(frozen=True)
class Sources:
    category: str
    t2: int
    paths: dict[str, Path]
    identity: dict


def load(prepared: Path, *, metadata: Path | None = None, reviews: Path | None = None) -> Sources:
    prepared = prepared.resolve(strict=True)
    data = read_json(prepared)
    if data.get('format') != 'recarena-amazon-prepared-v1' or data.get('status') != 'complete':
        raise ValueError('Expected a complete recarena-amazon-prepared-v1 prepared.json')
    split = data['time_split']
    t2 = split.get('T2')
    if type(t2) is not int or split.get('timestamp_unit') != 'milliseconds':
        raise ValueError('prepared.json must supply an integer T2 in milliseconds')
    paths = {key: (prepared.parent / data['files'][key]).resolve(strict=True)
             for key in ('metadata', 'train', 'valid', 'test')}
    paths['raw_metadata'] = (metadata or Path(data['sources']['metadata'])).resolve(strict=True)
    paths['raw_reviews'] = (reviews or Path(data['sources']['reviews'])).resolve(strict=True)
    identity = {'prepared': {'path': str(prepared), 'sha256': file_hash(prepared)},
                'category': data['category'], 'time_split': split, 'files': {}}
    for name, path in paths.items():
        stat = path.stat()
        # Large original inputs are identified by path/size/mtime, not claimed to be content hashed.
        identity['files'][name] = {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    return Sources(data['category'], t2, paths, identity)
