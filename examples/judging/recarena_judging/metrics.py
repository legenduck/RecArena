"""Arithmetic over judgments; no model calls, catalog access or platform imports."""
from collections import Counter


def ratio(judged: list[dict]) -> float | None:
    met = sum(j['verdict'] == 'met' for j in judged)
    return met / len(judged) if judged else None


def hit(chosen: str, target: str) -> int:
    if not isinstance(chosen, str) or not chosen.strip() or not isinstance(target, str) or not target.strip():
        raise ValueError('Hit requires both parent_asin values')
    return int(chosen == target)


def scores(ps: list[dict], qc: list[dict] | None = None, hit_value: int | None = None) -> dict:
    result = {'ps': ratio(ps), 'ps_by_axis': {axis: ratio([c for c in ps if c['axis'] == axis])
              for axis in sorted({c['axis'] for c in ps})},
              'ps_not_applicable': sum(c['verdict'] == 'not_applicable' for c in ps)}
    if qc is not None:
        result.update(qc=ratio(qc), qc_all_met=all(c['verdict'] == 'met' for c in qc) if qc else None)
    if hit_value is not None:
        result['hit'] = hit_value
    return result


def average(values: list) -> dict:
    valid = [v for v in values if v is not None]
    return {'value': sum(valid) / len(valid) if valid else None,
            'numerator': sum(valid), 'denominator': len(valid), 'unavailable': len(values) - len(valid)}


def verdict_counts(judged: list[dict]) -> dict:
    return dict(Counter(j['verdict'] if j['verdict'] != 'not_met'
                        else f'not_met_{j["not_met_reason"]}' for j in judged))


def criterion_ratio(judged: list[dict]) -> dict:
    return {'value': ratio(judged), 'numerator': sum(c['verdict'] == 'met' for c in judged),
            'denominator': len(judged),
            'not_applicable': sum(c['verdict'] == 'not_applicable' for c in judged)}


def rollout_hit(rollouts: list[dict]) -> dict:
    values = [int(any(hit(asin, row['target_parent_asin'])
                      for asin in row['purchased_parent_asins'])) for row in rollouts]
    purchased = sum(bool(row['purchased_parent_asins']) for row in rollouts)
    return {**average(values), 'purchased': purchased, 'no_purchase': len(rollouts) - purchased}


def summarize(jobs: list[dict], results: dict[str, dict], states: dict,
              rollouts: list[dict] | None = None) -> dict:
    rollouts = [] if rollouts is None else rollouts
    groups = {}
    task_types = {j['task']['type'] for j in jobs} | {r['task_type'] for r in rollouts}
    for task_type in sorted(task_types):
        selected = [j for j in jobs if j['task']['type'] == task_type]
        completed = [results[j['key']] for j in selected if j['key'] in results]
        failed = sum(j['key'] not in results and states.get(j['key'], {}).get('status') == 'failed' for j in selected)
        group = {'selected': len(selected), 'completed': len(completed), 'failed': failed,
                 'unfinished': len(selected) - len(completed) - failed,
                 'ps': average([r['scores']['ps'] for r in completed]),
                 'ps_verdicts': verdict_counts([c for r in completed for c in r['ps']])}
        if task_type == 'TF_attribute_specific':
            qc = [c for r in completed for c in r['qc']]
            group.update(qc=average([r['scores']['qc'] for r in completed]),
                         qc_all_met=average([r['scores']['qc_all_met'] for r in completed]),
                         qc_verdicts=verdict_counts(qc),
                         qc_by_condition={k: criterion_ratio([c for c in qc if c['condition'] == k])
                                          for k in sorted({c['condition'] for c in qc})},
                         hit=None)
            tf_rollouts = [r for r in rollouts if r['task_type'] == task_type]
            if tf_rollouts:
                group['hit'] = rollout_hit(tf_rollouts)
        groups[task_type] = group
    return {'format': 'recarena-judging-summary-v2', 'selected': len(jobs), 'completed': len(results),
            'rollouts': len(rollouts),
            'failed': sum(g['failed'] for g in groups.values()), 'unfinished': sum(g['unfinished'] for g in groups.values()),
            'final': len(results) == len(jobs), 'groups': groups,
            'scope': {'ps_qc': 'completed choices only; unavailable ratios excluded with counts',
                      'hit': 'all supplied evaluated TFA rollouts, including no purchase; null without TFA rollout input'},
            'definitions': {'ps': 'met / all preference criteria, excluding request-budget criteria; not_applicable contributes 0',
                            'qc': 'met / all explicit criteria, including saved request-budget criteria; not_applicable contributes 0',
                            'qc_all_met': 'every QC criterion is met',
                            'hit': 'TFA rollouts purchasing the exact target parent_asin / all evaluated TFA rollouts'}}
