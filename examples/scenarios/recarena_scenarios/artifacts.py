"""Frozen preparation inputs, resumable successful stages, and atomic dataset publication."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from recarena_llm import jsonio
from recarena_llm.jsonio import now, dump, digest, file_hash, read_json, write_json


def implementation_identity() -> dict:
    root = Path(__file__).parent
    return {**{p.name: file_hash(p) for p in sorted(root.glob('*.py'))}, **jsonio.implementation_identity()}


@contextmanager
def run_lock(directory: Path):
    """Only the generator holds this OS lock; a killed process releases it automatically."""
    with (directory / 'records' / '.generate.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This run already has an active generator') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def freeze(directory: Path, *, config: dict, sources: dict, audit: dict, samples: list[dict]) -> dict:
    records = directory / 'records'
    records.mkdir(exist_ok=True)
    package = Path(__file__).parent
    resources = {}
    for folder in ('prompts', 'schemas'):
        for path in sorted((package / folder).iterdir()):
            if not path.is_file():
                continue
            dest = records / folder / path.name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, dest)
            resources[f'{folder}/{path.name}'] = file_hash(dest)
    entries = []
    for sample in samples:
        key = hashlib.sha256(sample['user_id'].encode()).hexdigest()[:24]
        history = {k: sample[k] for k in ('user_id', 'main_category', 'reviews')}
        files = {}
        for name, value in (('history', history), ('target', sample['target'])):
            path = directory / 'work' / 'inputs' / key / f'{name}.json'
            write_json(path, value)
            files[name] = {'path': str(path.relative_to(directory)), 'sha256': file_hash(path)}
        entries.append({'key': key, 'user_id': sample['user_id'], 'files': files})
    manifest = {'format': 'recarena-scenario-run-v3', 'run_id': str(uuid.uuid4()), 'created_at': now(),
                'config': config, 'sources': sources, 'sampling': audit, 'entries': entries,
                'resources': resources, 'implementation': implementation_identity()}
    write_json(records / 'run.json', manifest)
    write_json(records / 'run.sha256.json', {'sha256': file_hash(records / 'run.json')})
    write_json(records / 'status.json', {'status': 'prepared', 'updated_at': now(), 'users': {}})
    return manifest


class Run:
    """One frozen run owns its inputs, status and successful-stage receipts."""
    def __init__(self, directory: Path):
        self.directory = directory.resolve(strict=True)
        self.records = self.directory / 'records'
        path = self.records / 'run.json'
        if file_hash(path) != read_json(self.records / 'run.sha256.json')['sha256']:
            raise ValueError('Frozen run.json changed; prepare a new run')
        self.manifest = read_json(path)
        if self.manifest.get('format') != 'recarena-scenario-run-v3':
            raise ValueError('This run uses an unsupported format; keep it unchanged and prepare a new run')
        if self.manifest['implementation'] != implementation_identity():
            raise ValueError('Scenario implementation changed; resume with the original code or prepare a new run')
        for relative, expected in self.manifest['resources'].items():
            if file_hash(self.records / relative) != expected:
                raise ValueError(f'Frozen resource changed: {relative}')
        for entry in self.manifest['entries']:
            for item in entry['files'].values():
                if file_hash(self.directory / item['path']) != item['sha256']:
                    raise ValueError(f'Frozen input changed: {item["path"]}')
        self.config = self.manifest['config']
        self.state = read_json(self.records / 'status.json')

    def input(self, entry: dict, name: str):
        return read_json(self.directory / entry['files'][name]['path'])

    def prompt(self, name: str) -> str:
        return (self.records / 'prompts' / f'{name}.md').read_text()

    def schema(self, name: str) -> dict:
        return read_json(self.records / 'schemas' / f'{name}.json')

    def cached(self, key: str, stage: str, inputs):
        path = self.directory / 'work' / 'stages' / key / f'{stage}.json'
        if not path.exists():
            return None
        record = read_json(path)
        if record['input_sha256'] != digest(inputs) or record['value_sha256'] != digest(record['value']):
            raise ValueError(f'Changed cached stage: {key}/{stage}; refusing to reuse it')
        return record['value']

    def save(self, key: str, stage: str, inputs, value):
        write_json(self.directory / 'work' / 'stages' / key / f'{stage}.json',
                   {'input_sha256': digest(inputs), 'value_sha256': digest(value), 'value': value})
        return value

    def status(self, status: str, *, key: str | None = None, error: str | None = None):
        if key is None:
            self.state['status'] = status
        else:
            self.state['users'][key] = {'status': status, 'error': error, 'updated_at': now()}
        self.state['updated_at'] = now()
        write_json(self.records / 'status.json', self.state)


def check_dataset(directory: Path, run_id: str) -> dict:
    manifest = read_json(directory / 'manifest.json')
    if manifest.get('format') != 'recarena-scenario-dataset-v3':
        raise ValueError('Expected a recarena-scenario-dataset-v3 dataset')
    if manifest['run_id'] != run_id or manifest['status'] != 'complete':
        raise ValueError('Dataset belongs to another run or is incomplete')
    for entry in manifest['files'].values():
        path = directory / entry['path']
        if file_hash(path) != entry['sha256']:
            raise ValueError(f'Dataset file changed: {path.name}')
        with path.open() as stream:
            if sum(1 for _ in stream) != entry['records']:
                raise ValueError(f'Dataset count changed: {path.name}')
    return manifest


def publish(run: Run, results: list[dict]) -> dict:
    expected = [e['user_id'] for e in run.manifest['entries']]
    if [r['user_id'] for r in results] != expected:
        raise ValueError('Cannot publish: the complete selected user set is required')
    target = run.directory / 'dataset'
    if target.exists():
        return check_dataset(target, run.manifest['run_id'])
    staging = Path(tempfile.mkdtemp(prefix='.dataset-', dir=run.directory / 'work'))
    try:
        histories = [run.input(e, 'history') for e in run.manifest['entries']]
        profiles = [{'user_id': r['user_id'], **r['profile']} for r in results]
        tasks = []
        for result in results:
            for group in result['tasks']:
                for task in group['tasks']:
                    task_id = digest([run.manifest['run_id'], result['user_id'], task['type']])[:32]
                    tasks.append({**{k: v for k, v in group.items() if k != 'tasks'}, **task,
                                  'task_id': task_id, 'user_id': result['user_id']})
        requests = [{'task_id': t['task_id'], 'request': t['request']} for t in tasks]
        manifest = {'format': 'recarena-scenario-dataset-v3', 'status': 'complete',
                    'run_id': run.manifest['run_id'], 'created_at': now(), 'users': len(results),
                    'tasks': len(tasks), 'selected_users': expected, 'config': run.config,
                    'sampling': run.manifest['sampling'], 'sources': run.manifest['sources'],
                    'resources': run.manifest['resources'], 'implementation': run.manifest['implementation'],
                    'files': {}, 'semantic_quality': 'not_automatically_verified'}
        for name, values in (('histories', histories), ('profiles', profiles), ('tasks', tasks), ('requests', requests)):
            path = staging / f'{name}.jsonl'
            with path.open('w', encoding='utf-8') as stream:
                for value in values:
                    stream.write(dump(value) + '\n')
            manifest['files'][name] = {'path': path.name, 'records': len(values), 'sha256': file_hash(path)}
        write_json(staging / 'manifest.json', manifest)
        check_dataset(staging, manifest['run_id'])
        os.replace(staging, target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)
