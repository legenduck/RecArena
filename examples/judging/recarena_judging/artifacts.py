"""Frozen judging inputs, successful criteria and complete output publication."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from recarena_llm import jsonio
from recarena_llm.jsonio import digest, dump, file_hash, now, read_json, write_json


def implementation_identity() -> dict:
    root = Path(__file__).parent
    return {**{p.name: file_hash(p) for p in sorted(root.glob('*.py'))}, **jsonio.implementation_identity()}


@contextmanager
def run_lock(directory: Path):
    with (directory / 'records/.judge.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This run already has an active judge') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def freeze(directory: Path, jobs: list[dict], sources: dict, config: dict, rollouts: list[dict]) -> dict:
    records = directory / 'records'
    records.mkdir()
    package = Path(__file__).parent
    resources = {}
    for name in ('prompts/attribute_judge_system.md', 'schemas/attribute.json'):
        dest = records / name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(package / name, dest)
        resources[name] = file_hash(dest)
    write_json(directory / 'work/jobs.json', jobs)
    write_json(directory / 'work/rollouts.json', rollouts)
    manifest = {'format': 'recarena-judging-run-v2', 'run_id': uuid.uuid4().hex,
                'created_at': now(), 'config': config, 'sources': sources,
                'jobs_sha256': file_hash(directory / 'work/jobs.json'),
                'rollouts_sha256': file_hash(directory / 'work/rollouts.json'),
                'resources': resources, 'implementation': implementation_identity()}
    write_json(records / 'run.json', manifest)
    write_json(records / 'run.sha256.json', {'sha256': file_hash(records / 'run.json')})
    write_json(records / 'status.json', {'status': 'prepared', 'choices': {}, 'updated_at': now()})
    return manifest


class Run:
    def __init__(self, directory: Path):
        self.directory = directory.resolve(strict=True)
        self.records = self.directory / 'records'
        path = self.records / 'run.json'
        if file_hash(path) != read_json(self.records / 'run.sha256.json')['sha256']:
            raise ValueError('Frozen run changed; prepare a new output directory')
        self.manifest = read_json(path)
        if self.manifest.get('format') != 'recarena-judging-run-v2':
            raise ValueError('Unsupported judging run format')
        if self.manifest['implementation'] != implementation_identity():
            raise ValueError('Judging implementation changed; use the original code or prepare a new run')
        for name, expected in self.manifest['resources'].items():
            if file_hash(self.records / name) != expected:
                raise ValueError(f'Frozen resource changed: {name}')
        if file_hash(self.directory / 'work/jobs.json') != self.manifest['jobs_sha256']:
            raise ValueError('Frozen judging inputs changed')
        if file_hash(self.directory / 'work/rollouts.json') != self.manifest['rollouts_sha256']:
            raise ValueError('Frozen rollout inputs changed')
        self.jobs = read_json(self.directory / 'work/jobs.json')
        self.rollouts = read_json(self.directory / 'work/rollouts.json')
        self.config = self.manifest['config']
        self.state = read_json(self.records / 'status.json')
        self.prompt = (self.records / 'prompts/attribute_judge_system.md').read_text()
        self.schema = read_json(self.records / 'schemas/attribute.json')

    def cached(self, key: str, name: str, inputs):
        path = self.directory / 'work/receipts' / key / f'{name}.json'
        if not path.exists():
            return None
        entry = read_json(path)
        if entry['input_sha256'] != digest(inputs) or entry['value_sha256'] != digest(entry['value']):
            raise ValueError(f'Changed cached judgment: {key}/{name}')
        return entry['value']

    def save(self, key: str, name: str, inputs, value):
        write_json(self.directory / 'work/receipts' / key / f'{name}.json',
                   {'input_sha256': digest(inputs), 'value_sha256': digest(value), 'value': value})
        return value

    def status(self, status: str, key: str | None = None, error: str | None = None):
        if key is None:
            self.state['status'] = status
        else:
            self.state['choices'][key] = {'status': status, 'error': error, 'updated_at': now()}
        self.state['updated_at'] = now()
        write_json(self.records / 'status.json', self.state)

    def completed(self) -> dict:
        result = {}
        for job in self.jobs:
            value = self.cached(job['key'], 'result', job)
            if value is not None:
                result[job['key']] = value
        return result


def publish(run: Run, results: dict, summary: dict):
    if len(results) != len(run.jobs):
        raise ValueError('Cannot publish incomplete judgments')
    target = run.directory / 'dataset'
    if target.exists():
        manifest = read_json(target / 'manifest.json')
        if manifest['run_id'] != run.manifest['run_id']:
            raise ValueError('Published dataset belongs to another run')
        for name, expected in manifest['files'].items():
            if file_hash(target / name) != expected:
                raise ValueError(f'Published file changed: {name}')
        return
    staging = Path(tempfile.mkdtemp(prefix='.dataset-', dir=run.directory / 'work'))
    try:
        (staging / 'results.jsonl').write_text(''.join(dump(results[j['key']]) + '\n' for j in run.jobs))
        (staging / 'rollouts.jsonl').write_text(''.join(dump(row) + '\n' for row in run.rollouts))
        write_json(staging / 'summary.json', summary)
        write_json(staging / 'manifest.json', {'format': 'recarena-judging-dataset-v2',
            'run_id': run.manifest['run_id'], 'status': 'complete', 'choices': len(results),
            'rollouts': len(run.rollouts),
            'created_at': now(), 'config': run.config, 'sources': run.manifest['sources'],
            'resources': run.manifest['resources'], 'implementation': run.manifest['implementation'],
            'files': {name: file_hash(staging / name) for name in ('results.jsonl', 'rollouts.jsonl', 'summary.json')}})
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
