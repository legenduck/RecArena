"""Export serialization and file-integrity checks, independent of research metrics."""
import csv
import hashlib
import json
from pathlib import Path


def strict_json(text):
    def invalid(value): raise ValueError('Non-finite JSON value: '+value)
    return json.loads(text,parse_constant=invalid)


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path,rows,fields):
    with path.open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key:json.dumps(row.get(key),sort_keys=True,ensure_ascii=False,allow_nan=False) if isinstance(row.get(key),(dict,list)) else row.get(key) for key in fields})


def write_json_array(path,rows):
    with path.open('x',encoding='utf-8') as stream:
        stream.write('[')
        for index,row in enumerate(rows):
            if index: stream.write(',')
            json.dump(row,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
        stream.write(']\n')


def read_csv(path):
    integers={'quantity','total_quantity','unit_price_minor','total_price_minor','repetition','seed'}
    with path.open(newline='',encoding='utf-8') as stream:
        result=[]
        for row in csv.DictReader(stream):
            result.append({key:(None if value=='' else int(value) if key in integers else strict_json(value) if key in {'selected_options','connection','limits','entry_config','entry_snapshot','items','totals_by_currency'} else value) for key,value in row.items()})
        return result


def read_jsonl(path):
    with path.open(encoding='utf-8') as stream:
        return [strict_json(line) for line in stream if line.strip()]


def verify_export(directory):
    root=Path(directory).resolve()
    manifest=strict_json((root/'export_manifest.json').read_text())
    if manifest.get('schema_version') not in {'1.0','2.0'}:
        raise ValueError('Unsupported export schema version')
    expected=set()
    for entry in manifest['files']:
        path=(root/entry['path']).resolve()
        if not path.is_relative_to(root) or path in expected or path==root/'export_manifest.json':
            raise ValueError('Invalid export file path')
        expected.add(path)
        if path.stat().st_size!=entry['size_bytes'] or file_hash(path)!=entry['sha256']:
            raise ValueError('Export checksum mismatch: '+entry['path'])
    actual={p.resolve() for p in root.rglob('*') if p.is_file() and p.resolve()!=root/'export_manifest.json'}
    if expected!=actual:
        raise ValueError('Export file inventory differs from manifest')
    return manifest
