"""JSON records and file identity used by research model calls."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(value, *, pretty=False) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      indent=2 if pretty else None, separators=None if pretty else (',', ':'))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path: Path):
    def reject(value):
        raise ValueError(f'Non-finite JSON value: {value}')
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=reject)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(dump(value, pretty=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def implementation_identity() -> dict:
    root = Path(__file__).parent
    return {"llm/" + p.name: file_hash(p) for p in sorted(root.glob("*.py"))}
