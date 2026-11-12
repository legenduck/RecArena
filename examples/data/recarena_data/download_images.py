"""Optional image download for self hosting; never called during catalog import or serving."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb
from pydantic import TypeAdapter

from recarena_contracts.models import ID
from recarena_data.image_sources import image_entries

MAX_BYTES = 32 * 1024 * 1024
_identifier = TypeAdapter(ID)


def download_images(*, metadata, root, workers=8):
    if workers < 1:
        raise ValueError('workers must be positive')
    metadata = Path(metadata).resolve(strict=True)
    root = Path(root).resolve()
    # A new collection prevents accidental replacement of already served files.
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'downloads.parquet'

    def fetch(entry):
        parent, index, url = entry
        relative = f'large/{parent[-2:]}/{parent}_{index:02d}.jpg'
        destination = root / relative
        try:
            with urlopen(Request(url, headers={'User-Agent': 'RecArena image preparation'}), timeout=30) as response:
                content = response.read(MAX_BYTES + 1)
            if not content or len(content) > MAX_BYTES:
                raise ValueError('Empty or oversized image')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(content)
            return parent, index, relative, True, len(content), url, None
        except (OSError, ValueError) as error:
            return parent, index, relative, False, 0, url, str(error)

    with duckdb.connect() as reader, duckdb.connect() as writer, ThreadPoolExecutor(max_workers=workers) as pool:
        writer.execute('CREATE TABLE downloads(parent_asin VARCHAR, idx INTEGER, path VARCHAR, '
                       'ok BOOLEAN, bytes BIGINT, url VARCHAR, error VARCHAR)')
        rows = reader.execute('SELECT parent_asin,json FROM read_parquet(?) ORDER BY parent_asin', [str(metadata)])
        total = failed = 0
        while batch := rows.fetchmany(64):
            entries = [(_identifier.validate_python(parent), index, url)
                for parent, raw in batch for index, url in image_entries(json.loads(raw))]
            results = list(pool.map(fetch, entries))
            if results:
                writer.executemany('INSERT INTO downloads VALUES (?,?,?,?,?,?,?)', results)
            total += len(results)
            failed += sum(not row[3] for row in results)
        writer.execute('COPY downloads TO ? (FORMAT PARQUET)', [str(source)])
    print(json.dumps({'stage': 'image_download', 'total': total, 'downloaded': total - failed, 'failed': failed}), flush=True)
    return source
