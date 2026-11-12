"""Build page-level criteria from saved task data, never from a second LLM."""

TASK_TYPES = ('AS', 'TF_attribute_specific')
VERDICTS = ('met', 'not_met', 'not_applicable')
NOT_MET_REASONS = ('contradicted', 'absent')


def is_request_budget(criterion: dict) -> bool:
    return criterion['axis'] == 'price' and criterion.get('origin') == 'request'


def preference(task: dict) -> list[dict]:
    return [{'id': c['id'], 'axis': c['axis'], 'origin': c.get('origin'),
             'criterion': c['criterion']} for c in task['checklist']['criteria'] if not is_request_budget(c)]


def compliance(task: dict) -> list[dict]:
    if task['type'] == 'AS':
        return []
    brand = task['tf']['brand']
    product_type = task['scenario']['product_type']
    result = [
        {'id': 'R_brand', 'condition': 'brand', 'value': brand,
         'criterion': f'Is a product of the brand "{brand}".'},
        {'id': 'R_type', 'condition': 'product_type', 'value': product_type,
         'criterion': f'Is the requested type of product: {product_type}.'}]
    for number, feature in enumerate(task['tf']['attribute_features'], 1):
        result.append({'id': f'R_feature{number}', 'condition': 'feature', 'value': feature,
                       'criterion': f'Has this feature: {feature}.'})
    for criterion in task['checklist']['criteria']:
        if is_request_budget(criterion):
            result.append({'id': f'R_budget_{criterion["id"]}', 'condition': 'budget',
                           'value': criterion['criterion'], 'criterion': criterion['criterion']})
    return result


def validate_attribute(value: dict) -> list[str]:
    problems = []
    if value['verdict'] == 'not_met' and value['not_met_reason'] not in NOT_MET_REASONS:
        problems.append('A not_met verdict needs not_met_reason "contradicted" or "absent".')
    if value['verdict'] != 'not_met' and value['not_met_reason'] is not None:
        problems.append('not_met_reason must be null unless the verdict is not_met.')
    if not value['evidence'].strip():
        problems.append('evidence is empty.')
    return problems
