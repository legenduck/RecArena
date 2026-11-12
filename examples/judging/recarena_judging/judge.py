"""Apply the same page-and-criterion judge to PS and QC; Hit never calls a model."""
import asyncio

from recarena_llm.jsonio import digest
from recarena_llm.transport import body, checked_json
from . import criteria, metrics


async def judge_choice(run, job: dict, transport, semaphore: asyncio.Semaphore) -> dict:
    task, selected, page = job['task'], job['selection'], job['page']
    pending = [('ps', c) for c in criteria.preference(task)]
    pending += [('qc', c) for c in criteria.compliance(task)]

    async def criterion(kind: str, item: dict):
        name = kind + '_' + digest(item['id'])
        request = body(run.config['llm'], run.prompt, {'PAGE': page, 'CRITERION': item['criterion']},
                       run.schema, 'attribute')
        if run.config['llm']['reasoning'] != 'omit':
            request['reasoning']['summary'] = 'auto'
        response = run.cached(job['key'], name, request)
        if response is None:
            async with semaphore:
                response = await checked_json(transport, job['key'], name, request, criteria.validate_attribute,
                                              run.config['judging']['repairs'])
            run.save(job['key'], name, request, response)
        return {'kind': kind, **item, **response}

    judged = []
    if pending:
        judged.append(await criterion(*pending[0]))
        calls = [asyncio.create_task(criterion(*item)) for item in pending[1:]]
        try:
            judged += await asyncio.gather(*calls)
        finally:
            for call in calls:
                call.cancel()
            await asyncio.gather(*calls, return_exceptions=True)
    ps = [c for c in judged if c['kind'] == 'ps']
    qc = [c for c in judged if c['kind'] == 'qc'] if task['type'] == 'TF_attribute_specific' else None
    hit_value = metrics.hit(selected['parent_asin'], task['target_parent_asin']) if qc is not None else None
    result = {'choice_id': selected['choice_id'], 'task_id': task['task_id'], 'user_id': task['user_id'],
              'task_type': task['type'], 'parent_asin': selected['parent_asin'], 'selection': selected,
              'request': task['request'], 'page': page, 'ps': ps, 'scores': metrics.scores(ps, qc, hit_value)}
    if qc is not None:
        result.update(qc=qc, target_parent_asin=task['target_parent_asin'])
    return run.save(job['key'], 'result', job, result)
