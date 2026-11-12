"""Read completed task rows, explicit choices and the fixed common catalog snapshot."""
import json
from pathlib import Path

import duckdb

from recarena_llm.jsonio import digest, file_hash, read_json
from .criteria import TASK_TYPES

PAGE_FIELDS = ('title', 'store', 'price', 'categories', 'features', 'description', 'details')


def rows(path: Path):
    def reject_number(value):
        raise ValueError(f'Invalid JSON number: {value}')

    with path.open(encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line, parse_constant=reject_number)
            if not isinstance(value, dict):
                raise ValueError(f'{path}:{number}: expected an object')
            yield value


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')


def tasks(path: Path) -> dict:
    result = {}
    for task in rows(path):
        for field in ('task_id', 'user_id', 'request'):
            require_text(task.get(field), field)
        if task.get('type') not in TASK_TYPES:
            raise ValueError(f'Unsupported task type: {task.get("type")}')
        if task['task_id'] in result:
            raise ValueError(f'Duplicate task_id: {task["task_id"]}')
        checklist = (task.get('checklist') or {}).get('criteria')
        if not isinstance(checklist, list):
            raise ValueError('checklist.criteria must be an array')
        ids = set()
        for criterion in checklist:
            if not isinstance(criterion, dict):
                raise ValueError('Each checklist criterion must be an object')
            for field in ('id', 'axis', 'criterion'):
                require_text(criterion.get(field), f'checklist.{field}')
            if criterion['id'] in ids:
                raise ValueError('Duplicate checklist criterion id')
            ids.add(criterion['id'])
        if task['type'] == 'TF_attribute_specific':
            require_text(task.get('target_parent_asin'), 'target_parent_asin')
            require_text(task.get('scenario', {}).get('product_type'), 'scenario.product_type')
            require_text(task.get('tf', {}).get('brand'), 'tf.brand')
            features = task['tf'].get('attribute_features')
            if not isinstance(features, list) or not 2 <= len(features) <= 3:
                raise ValueError('TFA needs two or three saved attribute_features')
            for feature in features:
                require_text(feature, 'tf.attribute_features entry')
        result[task['task_id']] = task
    if not result:
        raise ValueError('No task rows')
    return result


def selections(path: Path, task_map: dict, *, allow_empty: bool = False) -> list[dict]:
    result, seen = [], set()
    for row in rows(path):
        for name in ('choice_id', 'task_id', 'parent_asin'):
            require_text(row.get(name), name)
        if row['choice_id'] in seen:
            raise ValueError(f'Duplicate choice_id: {row["choice_id"]}')
        if row['task_id'] not in task_map:
            raise ValueError(f'Unknown task_id: {row["task_id"]}')
        seen.add(row['choice_id'])
        result.append(row)
    if not result and not allow_empty:
        raise ValueError('No selection rows')
    return result


def rollouts(path: Path, task_map: dict) -> list[dict]:
    """One completed evaluation attempt, including an explicit empty purchase list."""
    result, seen = [], set()
    for row in rows(path):
        for name in ('rollout_id', 'task_id'):
            require_text(row.get(name), name)
        if row['rollout_id'] in seen:
            raise ValueError(f'Duplicate rollout_id: {row["rollout_id"]}')
        if row['task_id'] not in task_map:
            raise ValueError(f'Unknown rollout task_id: {row["task_id"]}')
        purchased = row.get('purchased_parent_asins')
        if not isinstance(purchased, list):
            raise ValueError('purchased_parent_asins must be an array; use [] for no purchase')
        for parent_asin in purchased:
            require_text(parent_asin, 'purchased_parent_asins entry')
        task = task_map[row['task_id']]
        item = {'rollout_id': row['rollout_id'], 'task_id': row['task_id'],
                'task_type': task['type'], 'purchased_parent_asins': purchased}
        if task['type'] == 'TF_attribute_specific':
            item['target_parent_asin'] = task['target_parent_asin']
        seen.add(row['rollout_id'])
        result.append(item)
    if not result:
        raise ValueError('No rollout rows')
    return result


def catalog(prepared: Path, asins: set[str], config: dict) -> tuple[dict, dict]:
    document = read_json(prepared)
    if document.get('format') != 'recarena-amazon-prepared-v1' or document.get('status') != 'complete':
        raise ValueError('Expected a complete common prepared.json')
    split = document['time_split']
    if type(split.get('T2')) is not int or split.get('timestamp_unit') != 'milliseconds':
        raise ValueError('prepared.json must declare T2 in integer milliseconds')
    paths = {key: (prepared.parent / document['files'][key]).resolve(strict=True)
             for key in ('metadata', 'reviews_deduplicated')}

    def identity():
        return {k: {'path': str(p), 'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns}
                for k, p in paths.items()}

    before = identity()
    source = {'category': document['category'], 'T2_ms': split['T2'], 'files': before,
              'rating': 'finite 1–5 deduplicated reviews before T2, rounded to one decimal'}
    if not asins:
        return {}, source
    with duckdb.connect(config={'threads': config['threads'], 'memory_limit': config['memory_limit']}) as connection:
        connection.execute('CREATE TABLE wanted(parent_asin VARCHAR PRIMARY KEY)')
        connection.executemany('INSERT INTO wanted VALUES (?)', [(a,) for a in sorted(asins)])
        products = connection.execute('SELECT parent_asin,json FROM read_parquet(?) '
            'SEMI JOIN wanted USING(parent_asin)', [str(paths['metadata'])]).fetchall()
        if len({p[0] for p in products}) != len(products):
            raise ValueError('Duplicate parent_asin in prepared catalog')
        missing = asins - {p[0] for p in products}
        if missing:
            raise ValueError(f'Selected products missing from catalog: {sorted(missing)[:5]}')
        stats = {asin: (count, rating) for asin, count, rating in connection.execute(
            'SELECT parent_asin,count(*),avg(rating) FROM read_parquet(?) SEMI JOIN wanted USING(parent_asin) '
            'WHERE timestamp < ? AND isfinite(rating) AND rating BETWEEN 1 AND 5 GROUP BY parent_asin',
            [str(paths['reviews_deduplicated']), split['T2']]).fetchall()}
    if identity() != before:
        raise ValueError('Prepared catalog/reviews changed during page construction')
    pages = {}
    for asin, raw in products:
        product = json.loads(raw)
        if product.get('parent_asin') != asin:
            raise ValueError('Catalog row and source parent_asin differ')
        count, rating = stats.get(asin, (0, None))
        pages[asin] = {**{k: product.get(k) for k in PAGE_FIELDS},
                       'rating': round(rating, 1) if rating is not None else None, 'review_count': count}
    return pages, source


def load(task_path: Path, selection_path: Path, prepared: Path, config: dict,
         rollout_path: Path | None = None) -> tuple[list[dict], dict, list[dict]]:
    paths = {'tasks': task_path.resolve(strict=True), 'selections': selection_path.resolve(strict=True),
             'prepared': prepared.resolve(strict=True)}
    if rollout_path is not None:
        paths['rollouts'] = rollout_path.resolve(strict=True)
    sources = {k: {'path': str(p), 'sha256': file_hash(p)} for k, p in paths.items()}
    task_map = tasks(paths['tasks'])
    outcomes = rollouts(paths['rollouts'], task_map) if rollout_path is not None else []
    chosen = selections(paths['selections'], task_map, allow_empty=bool(outcomes))
    pages, source = catalog(paths['prepared'], {s['parent_asin'] for s in chosen}, config)
    if any(file_hash(paths[k]) != info['sha256'] for k, info in sources.items()):
        raise ValueError('Judging inputs changed during preparation')
    jobs = [{'key': digest(s['choice_id']), 'selection': s, 'task': task_map[s['task_id']],
             'page': pages[s['parent_asin']]} for s in chosen]
    return jobs, {**sources, 'catalog': source}, outcomes
