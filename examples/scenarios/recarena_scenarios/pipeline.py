"""Prepare frozen research inputs, then generate profiles and tasks independently of agents."""
import argparse
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
import yaml

from . import profiles, sampling, sources, tasks
from .artifacts import Run, check_dataset, freeze, now, publish, read_json, run_lock, write_json
from recarena_llm.transport import Responses


def configuration(path: Path | None) -> dict:
    resource = Path(__file__).with_name('default.yaml')
    if not resource.exists():
        resource = Path(__file__).parents[1] / 'configs' / 'default.yaml'
    defaults = yaml.safe_load(resource.read_text())
    result = copy.deepcopy(defaults)
    custom = yaml.safe_load(path.read_text()) if path else {}
    if not isinstance(custom, dict):
        raise ValueError('Configuration must be a YAML mapping')
    for section, values in custom.items():
        if section not in result or not isinstance(values, dict) or values.keys() - result[section].keys():
            raise ValueError(f'Unknown or invalid configuration section: {section}')
        result[section].update(values)
    integers = {'selection': ('min_reviews', 'min_category_reviews', 'sample_size', 'threads'),
                'generation': ('concurrency',), 'llm': ('max_output_tokens',)}
    for section, names in integers.items():
        for name in names:
            if type(result[section][name]) is not int or result[section][name] < 1:
                raise ValueError(f'{section}.{name} must be a positive integer')
    for section, name in (('generation', 'profile_repairs'), ('generation', 'task_repairs'), ('llm', 'network_retries')):
        if type(result[section][name]) is not int or result[section][name] < 0:
            raise ValueError(f'{section}.{name} must be a nonnegative integer')
    selection, generation, llm = result['selection'], result['generation'], result['llm']
    if type(selection['seed']) is not int or type(selection['allow_new_targets']) is not bool:
        raise ValueError('seed must be an integer and allow_new_targets a boolean')
    if type(selection['target_min_rating']) not in (float, int) or not 1 <= selection['target_min_rating'] <= 5:
        raise ValueError('target_min_rating must be between 1 and 5')
    if not isinstance(selection['memory_limit'], str) or not selection['memory_limit'].strip():
        raise ValueError('memory_limit must be a nonempty DuckDB memory limit')
    if (not isinstance(generation['intents'], list) or not generation['intents'] or
        any(i not in ('as', 'tf') for i in generation['intents']) or
        len(generation['intents']) != len(set(generation['intents']))):
        raise ValueError('intents must contain as and/or tf without duplicates')
    if not isinstance(llm['model'], str) or not llm['model'].strip():
        raise ValueError('model must be explicit')
    if llm['reasoning'] not in ('omit', 'none', 'low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Unknown reasoning setting')
    if type(llm['timeout_seconds']) not in (int, float) or not 0 < llm['timeout_seconds'] < float('inf'):
        raise ValueError('timeout_seconds must be positive and finite')
    url = urlsplit(llm['base_url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base_url must be an HTTP(S) address without credentials/query/fragment')
    return result


def prepare(prepared: Path, output: Path, config: Path | None = None,
            metadata: Path | None = None, reviews: Path | None = None) -> dict:
    settings = configuration(config)
    inputs = sources.load(prepared, metadata=metadata, reviews=reviews)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        samples, audit = sampling.prepare_samples(inputs, settings['selection'], output / 'work')
        validator = Draft202012Validator(read_json(Path(__file__).with_name('schemas') / 'sample.json'))
        errors = list(validator.iter_errors(samples))
        if errors:
            raise ValueError('Selected sample does not satisfy the profile input contract: ' +
                             '; '.join(f'{list(e.path)}: {e.message}' for e in errors[:10]))
        for sample in samples:
            profiles.prepare_user(sample)  # Detect malformed dates/duplicate source records before paid calls.
        # Detect inputs modified during this preparation; do not publish a mixed source identity.
        if sources.load(prepared, metadata=metadata, reviews=reviews).identity != inputs.identity:
            raise ValueError('Source files changed during preparation')
        return freeze(output, config=settings, sources=inputs.identity, audit=audit, samples=samples)
    except BaseException as error:
        write_json(output / 'records' / 'status.json', {'status': 'preparation_failed', 'updated_at': now(),
                   'error_type': type(error).__name__, 'error': str(error)})
        raise


async def generate_users(run: Run, transport: Responses) -> list[dict]:
    entries = run.manifest['entries']
    results = [None] * len(entries)
    queue = asyncio.Queue()
    for index, entry in enumerate(entries):
        queue.put_nowait((index, entry))

    async def worker():
        while not queue.empty():
            index, entry = queue.get_nowait()
            key = entry['key']
            run.status('running', key=key)
            try:
                profile = await profiles.generate(run, entry, transport)
                generated = [await tasks.generate(run, entry, profile['profile'], intent, transport)
                             for intent in run.config['generation']['intents']]
                results[index] = {'user_id': entry['user_id'], 'profile': profile, 'tasks': generated}
                run.status('complete', key=key)
                print(f'Complete: {entry["user_id"]}', flush=True)
            except asyncio.CancelledError:
                run.status('cancelled', key=key)
                raise
            except Exception as error:
                status_code = getattr(error, 'status_code', None)
                # Provider authentication errors can echo credentials in their response message.
                detail = f'HTTP {status_code}' if status_code is not None else str(error)
                run.status('failed', key=key, error=f'{type(error).__name__}: {detail}')
                print(f'Failed: {entry["user_id"]}: {type(error).__name__}', flush=True)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(len(entries), run.config['generation']['concurrency']))]
    try:
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    if any(result is None for result in results):
        raise RuntimeError('Some selected users failed; successes are retained. No dataset was published. Resume this run after resolving the cause.')
    return results


async def generate(directory: Path) -> dict:
    with run_lock(directory):
        run = Run(directory)
        if (directory / 'dataset').exists():
            result = check_dataset(directory / 'dataset', run.manifest['run_id'])
            run.status('complete')
            return result
        # Import and credential lookup occur only after frozen inputs have passed validation.
        from openai import AsyncOpenAI
        key = os.environ.get('OPENAI_API_KEY')
        if not key:
            raise ValueError('Set OPENAI_API_KEY for generate; prepare needs no key')
        run.status('generating')
        try:
            async with AsyncOpenAI(api_key=key, base_url=run.config['llm']['base_url'], max_retries=0,
                                   timeout=run.config['llm']['timeout_seconds']) as client:
                results = await generate_users(run, Responses(client, run.records, run.config['llm']))
            manifest = publish(run, results)
            run.status('complete')
            return manifest
        except BaseException as error:
            run.status('cancelled' if isinstance(error, asyncio.CancelledError) else 'failed')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='Offline: select and freeze users, inputs, settings and prompts')
    prep.add_argument('--prepared', required=True, type=Path)
    prep.add_argument('--output', required=True, type=Path)
    prep.add_argument('--config', type=Path)
    prep.add_argument('--metadata', type=Path, help='Relocated original metadata; overrides prepared.json source path')
    prep.add_argument('--reviews', type=Path, help='Relocated original reviews; overrides prepared.json source path')
    gen = commands.add_parser('generate', help='Paid model calls; rerunning resumes successful stages')
    gen.add_argument('--run', required=True, type=Path)
    args = vars(parser.parse_args())
    try:
        if args.pop('command') == 'prepare':
            manifest = prepare(**args)
            print(f'Prepared {len(manifest["entries"])} users: {args["output"]}/records/run.json')
        else:
            manifest = asyncio.run(generate(args['run'].resolve()))
            print(f'Published {manifest["tasks"]} tasks: {args["run"]}/dataset/manifest.json')
    except KeyboardInterrupt:
        parser.exit(130, 'Cancelled; resume the same run to reuse successful stages.\n')
    except Exception as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    main()
