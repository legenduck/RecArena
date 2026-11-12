"""Scenario, shared preference checklist and AS/TFA request generation.

Models choose meanings and sources; code adds criterion ids and the fixed
budget check. Final tasks keep one request and its research context.
"""
from __future__ import annotations
import copy
import re
from typing import Any

from jsonschema import Draft202012Validator

FACT_GROUPS = ("equipment", "environment", "people", "personal_conditions", "history_statistics")


AXES = ("brand", "price", "review", "functional", "subjective")


CHECKLIST_AXES = ("background_facts", "usage_patterns") + AXES


BUDGET_SOURCE = "request.budget_range"


LISTING_FIELDS = ("title", "store", "categories", "description", "features", "details")


HARD_LIMIT = re.compile(r"\b(under|below|up to|no more than|at most|max(imum)?( of)?|not over)\s+(about\s+|around\s+)?\$?\d",
                        re.I)


TF_TAG = "[TF] "


STOPWORDS = {"the", "and", "with", "for", "of", "a", "an", "in", "on", "to", "from", "made", "by", "or"}


def profile_items(profile: dict) -> list[dict]:
    """Profile entries with ids such as bf.equipment.0, up.3, pp.functional.2 (array order)."""
    items: list[dict] = []
    facts = profile.get("background_facts") or {}
    for group in FACT_GROUPS:
        for i, item in enumerate(facts.get(group) or []):
            items.append({"id": f"bf.{group}.{i}", "section": "background_facts", "group": group, "item": item})
    for i, item in enumerate(profile.get("usage_patterns") or []):
        items.append({"id": f"up.{i}", "section": "usage_patterns", "item": item})
    prefs = profile.get("product_preferences") or {}
    for axis in AXES:
        for i, item in enumerate(prefs.get(axis) or []):
            items.append({"id": f"pp.{axis}.{i}", "section": "product_preferences", "axis": axis, "item": item})
    return items


def prompt_view(entry: dict, quotes: bool = True) -> dict:
    """What the model sees for one item. Price statistics keep their counts but not the per-review headers.
    quotes=False (the checklist) keeps each evidence review's id and type but not its quote:
    the profile item already states the attitude, so the checklist applies it rather than re-judging it."""
    view = {"id": entry["id"], "section": entry["section"]}
    for key in ("group", "axis"):
        if key in entry:
            view[key] = entry[key]
    content = copy.deepcopy(entry["item"])
    evidence = content.get("evidence")
    if entry.get("group") == "history_statistics" and isinstance(evidence, dict):
        content["evidence"] = {k: v for k, v in evidence.items() if k != "reviews"}
    elif not quotes and isinstance(evidence, dict):
        for review in evidence.get("reviews") or []:
            review.pop("quote", None)
    view.update(content)
    return view


def target_input(record: dict) -> dict:
    """What the steps may see of the seed: its catalog listing and price, never the user's review of it."""
    target = record.get("target") or {}
    product = target.get("product") or {}
    categories = product.get("categories") or []
    return {"parent_asin": target.get("parent_asin"),
            "listing": {k: product.get(k) for k in LISTING_FIELDS},
            "price": product.get("price"),
            "task_category": " > ".join(categories) if categories else (record.get("main_category") or ""),
            "brand_hint": (product.get("details") or {}).get("Brand")}


def parse_price(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def listing_text(listing: dict) -> str:
    parts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                parts.append(str(k)); walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None:
            parts.append(str(v))
    walk(listing)
    return " ".join(parts)


def tokens(text: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if t in STOPWORDS:
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)
    return out


def numbers_in(text: str) -> set[str]:
    """Whole numbers in the text, reading a thousands separator as part of the number (2,400 -> 2400)."""
    return set(re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)))


def check_budget_phrase(text: str, budget_range: list[int] | None, where: str) -> list[str]:
    problems = []
    if budget_range is None:
        if "$" in text:
            problems.append(f"{where}: BUDGET_RANGE is null, so do not mention a price.")
        return problems
    if HARD_LIMIT.search(text):
        problems.append(f"{where}: present the budget as the range the user has in mind, not as a limit.")
    numbers = numbers_in(text)
    if any(str(n) not in numbers for n in budget_range):
        problems.append(f"{where}: mention the price range {budget_range[0]}–{budget_range[1]}.")
    return problems


def validate_scenario(out: dict, item_ids: set[str], price: float | None) -> list[str]:
    problems: list[str] = []
    if not str(out.get("product_type") or "").strip():
        problems.append("product_type must be a nonempty string.")
    situation, sources = out.get("situation"), out.get("situation_sources") or []
    if situation is not None and not str(situation).strip():
        problems.append("Use null instead of an empty situation.")
    if situation is None and sources:
        problems.append("situation is null, so situation_sources must be [].")
    if situation is not None and not sources:
        problems.append("A situation needs at least one supporting PROFILE_ITEMS id.")
    unknown = [s for s in sources if s not in item_ids]
    if unknown:
        problems.append(f"situation_sources contains ids that are not in PROFILE_ITEMS: {unknown}.")
    if len(sources) != len(set(sources)):
        problems.append("situation_sources contains duplicate ids.")
    budget = out.get("budget_range")
    if price is None:
        if budget is not None:
            problems.append("The target has no listed price, so budget_range must be null.")
    elif budget is None:
        problems.append("The target has a listed price, so budget_range must be [low, high].")
    elif not (isinstance(budget, list) and len(budget) == 2
              and all(isinstance(x, int) and not isinstance(x, bool) for x in budget)
              and 0 <= budget[0] <= budget[1]):
        problems.append("budget_range must be [low, high] with whole numbers and low <= high.")
    elif not budget[0] <= price <= budget[1]:
        problems.append(f"{TF_TAG}budget_range {budget} must include the target's listed price {price}.")
    return problems


def validate_checklist(out: dict, item_ids: set[str], budget_range: list[int] | None) -> list[str]:
    problems: list[str] = []
    used: set[str] = set()
    budget_criteria = []
    for k, c in enumerate(out.get("criteria") or [], 1):
        cid = c.get("id")
        if cid != f"C{k}":
            problems.append(f"Criterion ids must be sequential: expected C{k}, got {cid}.")
        if not str(c.get("criterion") or "").strip():
            problems.append(f"{cid}: criterion text is empty.")
        sources = c.get("sources") or []
        if not sources:
            problems.append(f"{cid}: sources is empty.")
        if BUDGET_SOURCE in sources:
            budget_criteria.append(c)
            if sources != [BUDGET_SOURCE]:
                problems.append(f"{cid}: the price-range criterion cites only {BUDGET_SOURCE}.")
            if c.get("axis") != "price":
                problems.append(f"{cid}: the price-range criterion uses axis price.")
        for s in sources:
            if s == BUDGET_SOURCE:
                continue
            if s not in item_ids:
                problems.append(f"{cid}: source {s} is not a PROFILE_ITEMS id.")
            used.add(s)
    if budget_range is None and budget_criteria:
        problems.append("BUDGET_RANGE is null, so remove the price-range criterion.")
    if budget_range is not None:
        if len(budget_criteria) != 1:
            problems.append("Write exactly one price-range criterion for BUDGET_RANGE.")
        elif any(str(n) not in numbers_in(budget_criteria[0].get("criterion") or "") for n in budget_range):
            problems.append(f"The price-range criterion must state {budget_range[0]} and {budget_range[1]}.")
    not_used = [e.get("id") for e in out.get("not_used") or []]
    unknown = sorted({e for e in not_used if e not in item_ids})
    if unknown:
        problems.append(f"not_used contains ids that are not in PROFILE_ITEMS: {unknown}.")
    dup = sorted({e for e in not_used if not_used.count(e) > 1})
    if dup:
        problems.append(f"These ids appear more than once in not_used: {dup}.")
    both = sorted(used & set(not_used))
    if both:
        problems.append(f"These ids are both cited and in not_used: {both}.")
    missing = sorted(item_ids - used - set(not_used))
    if missing:
        problems.append(f"Every PROFILE_ITEMS id must be cited or listed in not_used. Missing: {missing}.")
    blank = sorted(e.get("id") for e in out.get("not_used") or [] if not str(e.get("note") or "").strip())
    if blank:
        problems.append(f"Give each not_used entry a short note: {blank}.")
    return problems


def finalize_checklist(response: dict, budget_range: list[int] | None) -> dict:
    """Add code-owned fields without changing the model response or preference order."""
    result = copy.deepcopy(response)
    if budget_range is not None:
        low, high = budget_range
        result['criteria'].append({'axis': 'price',
            'criterion': f'Is priced between ${low} and ${high}.', 'sources': [BUDGET_SOURCE]})
    for number, criterion in enumerate(result['criteria'], 1):
        criterion['id'] = f'C{number}'
    return result


def validate_checklist_response(response: dict, item_ids: set[str]) -> list[str]:
    for number, criterion in enumerate(response['criteria'], 1):
        if BUDGET_SOURCE in criterion['sources']:
            return [f'Criterion {number}: sources must name PROFILE_ITEMS; '
                    f'{BUDGET_SOURCE} is not a profile item.']
    return validate_checklist(finalize_checklist(response, None), item_ids, None)


def validate_as(out: dict, brand: str | None, budget_range: list[int] | None) -> list[str]:
    text = str(out.get("request") or "")
    if not text.strip():
        return ["request is empty."]
    problems = check_budget_phrase(text, budget_range, "request")
    if brand and brand.lower() in text.lower():
        problems.append("The Alternative Selection request must not name the brand.")
    return problems


def validate_tf(out: dict, listing: dict, budget_range: list[int] | None) -> list[str]:
    brand = out.get("brand")
    if brand is None:
        if out.get("attribute_specific"):
            return ["brand is null, so attribute_specific must be null."]
        return []
    problems: list[str] = []
    features = out.get("attribute_features") or []
    text = str(out.get("attribute_specific") or "")
    if not text.strip():
        problems.append("attribute_specific is empty although a brand was identified.")
    else:
        if brand.lower() not in text.lower():
            problems.append(f"attribute_specific must name the brand {brand}.")
        problems += check_budget_phrase(text, budget_range, "attribute_specific")
    if not 2 <= len(features) <= 3:
        problems.append("attribute_features must list two or three features.")
    available = tokens(listing_text(listing))
    for f in features:
        extra = sorted(tokens(f) - available)
        if extra:
            problems.append(f"Feature '{f}' uses words not found in the listing: {extra}.")
    return problems


def attach_metadata(criteria: list[dict], items_by_id: dict[str, dict]) -> list[dict]:
    """Add origin, the sources' strengths, and the unique supporting-review count."""
    result = []
    for c in criteria:
        c = dict(c)
        if c.get("sources") == [BUDGET_SOURCE]:
            c.update(origin="request", source_strengths=[], review_count=0)
        else:
            reviews: set[str] = set()
            strengths = set()
            for s in c.get("sources") or []:
                item = items_by_id[s]["item"]
                if item.get("strength"):
                    strengths.add(item["strength"])
                for ev in (item.get("evidence") or {}).get("reviews") or []:
                    if ev.get("evidence_type") != "metadata":
                        reviews.add(ev["review_id"])
            c.update(origin="profile", source_strengths=sorted(strengths),
                     review_count=len(reviews))
        result.append(c)
    return result


async def generate(run, entry: dict, profile: dict, intent: str, transport) -> dict:
    """Each stage owns its projection; target reviews never enter a request."""
    from recarena_llm.transport import body, checked_json

    items = profile_items(profile)
    items_by_id = {item['id']: item for item in items}
    history = run.input(entry, 'history')
    original_target = run.input(entry, 'target')
    target = target_input({'main_category': history['main_category'], 'target': original_target})
    item_ids = set(items_by_id)

    async def step(name, payload, validate):
        schema_name = 'checklist_api' if name == 'checklist' else name
        request = body(run.config['llm'], run.prompt(name), payload, run.schema(schema_name), name)
        stage = f'{intent}_{name}'
        cached = run.cached(entry['key'], stage, request)
        if cached is not None:
            return cached
        value = await checked_json(transport, entry['key'], stage, request, validate,
                                   run.config['generation']['task_repairs'])
        return run.save(entry['key'], stage, request, value)

    def check_scenario(value):
        problems = validate_scenario(value, item_ids, parse_price(target['price']))
        return problems if intent == 'tf' else [p for p in problems if not p.startswith(TF_TAG)]

    scenario = await step('scenario', {'TARGET': {**target['listing'], 'price': target['price']},
                                      'PROFILE_ITEMS': [prompt_view(item) for item in items]}, check_scenario)
    budget = scenario['budget_range']
    checklist_response = await step('checklist', {'TASK_CATEGORY': target['task_category'],
        'SITUATION': scenario['situation'],
        'PROFILE_ITEMS': [prompt_view(item, quotes=False) for item in items]},
        lambda value: validate_checklist_response(value, item_ids))
    checklist = finalize_checklist(checklist_response, budget)
    Draft202012Validator(run.schema('checklist')).validate(checklist)
    result = {'intent': intent, 'target_parent_asin': target['parent_asin'],
              'target': original_target, 'task_category': target['task_category'], 'scenario': scenario,
              'checklist': {'criteria': attach_metadata(checklist['criteria'], items_by_id),
                            'not_used': checklist['not_used']}}
    shared = {'PRODUCT_TYPE': scenario['product_type'], 'SITUATION': scenario['situation'], 'BUDGET_RANGE': budget}
    if intent == 'tf':
        def check_tf(value):
            problems = validate_tf(value, target['listing'], budget)
            if value['brand'] is None:
                problems.append('The listing does not identify a brand, so no TF request can be written. '
                                'Do not invent one. This user cannot be replaced.')
            return problems

        value = await step('request_tf', {'TARGET': target['listing'], **shared},
                           check_tf)
        result['tf'] = {'brand': value['brand'], 'attribute_features': value['attribute_features']}
        result['tasks'] = [{'type': 'TF_attribute_specific', 'request': value['attribute_specific']}]
    else:
        value = await step('request_as', shared, lambda value: validate_as(value, target['brand_hint'], budget))
        result['tasks'] = [{'type': 'AS', 'request': value['request']}]
    return result
