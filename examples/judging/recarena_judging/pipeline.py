"""Prepare fixed judging inputs, run PS/QC, and recompute explicit summaries."""
import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from recarena_llm.jsonio import write_json
from recarena_llm.transport import Responses
from . import criteria, inputs, metrics
from .artifacts import Run, freeze, publish, run_lock
from .judge import judge_choice


def configuration(path: Path | None) -> dict:
    defaults = Path(__file__).with_name('default.yaml')
    if not defaults.exists():
        defaults = Path(__file__).parents[1] / 'configs/default.yaml'
    result = yaml.safe_load(defaults.read_text())
    custom = yaml.safe_load(path.read_text()) if path else {}
    if not isinstance(custom, dict):
        raise ValueError('Configuration must be a mapping')
    for section, values in custom.items():
        if section not in result or not isinstance(values, dict) or values.keys() - result[section].keys():
            raise ValueError(f'Unknown configuration section/setting: {section}')
        result[section].update(values)
    for section, key, minimum in [('data', 'threads', 1), ('judging', 'concurrency', 1),
                                 ('judging', 'repairs', 0), ('llm', 'max_output_tokens', 1),
                                 ('llm', 'network_retries', 0)]:
        if type(result[section][key]) is not int or result[section][key] < minimum:
            raise ValueError(f'{section}.{key} must be an integer >= {minimum}')
    for key in ('model',):
        inputs.require_text(result['llm'][key], 'llm.' + key)
    inputs.require_text(result['data']['memory_limit'], 'data.memory_limit')
    llm = result['llm']
    if llm['reasoning'] not in ('omit', 'none', 'low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Unknown reasoning setting')
    if type(llm['timeout_seconds']) not in (int, float) or not 0 < llm['timeout_seconds'] < float('inf'):
        raise ValueError('timeout_seconds must be positive and finite')
    url = urlsplit(llm['base_url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base_url must be an HTTP(S) address without credentials/query/fragment')
    return result


def prepare(tasks: Path, selections: Path, prepared: Path, output: Path, config: Path | None = None,
            rollouts: Path | None = None):
    settings = configuration(config)
    jobs, sources, outcomes = inputs.load(tasks, selections, prepared, settings['data'], rollouts)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    return freeze(output, jobs, sources, settings, outcomes)


def summarize(run: Run) -> dict:
    result = metrics.summarize(run.jobs, run.completed(), run.state['choices'], run.rollouts)
    write_json(run.directory / 'summary.json', result)
    return result


async def execute(run: Run, transport):
    semaphore = asyncio.Semaphore(run.config['judging']['concurrency'])
    queue = asyncio.Queue()
    for job in run.jobs:
        queue.put_nowait(job)

    async def worker():
        while not queue.empty():
            job = queue.get_nowait()
            key = job['key']
            try:
                if run.cached(key, 'result', job) is not None:
                    run.status('complete', key)
                    continue
                run.status('running', key)
                await judge_choice(run, job, transport, semaphore)
                run.status('complete', key)
            except asyncio.CancelledError:
                run.status('cancelled', key)
                raise
            except Exception as error:
                status = getattr(error, 'status_code', None)
                detail = f'HTTP {status}' if status is not None else str(error)
                run.status('failed', key, f'{type(error).__name__}: {detail}')
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(len(run.jobs), run.config['judging']['concurrency']))]
    try:
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


async def run_judging(directory: Path) -> dict:
    with run_lock(directory):
        run = Run(directory)
        run.status('judging')
        try:
            pending = [j for j in run.jobs if run.cached(j['key'], 'result', j) is None]
            needs_model = any(criteria.preference(j['task']) or criteria.compliance(j['task']) for j in pending)
            if needs_model:
                from openai import AsyncOpenAI
                key = os.environ.get('OPENAI_API_KEY')
                if not key:
                    raise ValueError('Set OPENAI_API_KEY for judging; prepare and summarize need no key')
                llm = run.config['llm']
                async with AsyncOpenAI(api_key=key, base_url=llm['base_url'], max_retries=0,
                                      timeout=llm['timeout_seconds']) as client:
                    await execute(run, Responses(client, run.records, llm))
            else:
                await execute(run, None)
            summary = summarize(run)
            if not summary['final']:
                raise RuntimeError('Some choices failed; successful judgments are retained. See summary.json and resume this run.')
            publish(run, run.completed(), summary)
            run.status('complete')
            return summary
        except BaseException:
            run.status('failed')
            summarize(run)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pre = commands.add_parser('prepare', help='Freeze task/choice/page inputs; no model calls')
    for name in ('tasks', 'selections', 'prepared', 'output'):
        pre.add_argument('--' + name, type=Path, required=True)
    pre.add_argument('--config', type=Path)
    pre.add_argument('--rollouts', type=Path,
                     help='Complete evaluated execution results, including no-purchase rows; required for aggregate TF Hit')
    for name in ('run', 'summarize'):
        commands.add_parser(name).add_argument('--run', type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        if command == 'prepare':
            value = prepare(**args)
            print(f'Prepared {value["run_id"]}: {args["output"]}/records/run.json')
        elif command == 'run':
            value = asyncio.run(run_judging(args['run']))
            print(f'Judged {value["completed"]}/{value["selected"]}: {args["run"]}/dataset/')
        else:
            with run_lock(args['run']):
                value = summarize(Run(args['run']))
            print(f'Completed {value["completed"]}/{value["selected"]}: {args["run"]}/summary.json')
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    main()
