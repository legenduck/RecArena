"""Review-grounded profiles: source projection, checks, and targeted repairs.

Grounding rules derive from profile v1.8.2; all reviews share one history and evidence count.
Transport and persistence are owned by llm.py and artifacts.py respectively.
"""
from __future__ import annotations
import copy
import json
import math
import re
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any, Iterable
from jsonschema import Draft202012Validator
from .artifacts import digest, dump
from recarena_llm.transport import output_text, checked_json

FACT_GROUPS = ("equipment", "environment", "people", "personal_conditions")


AXES = ("brand", "price", "review", "functional", "subjective")


class ValidationFailure(ValueError):
    pass


class SourceCheckFailure(ValidationFailure):
    """Some items cite evidence that does not match the source; the rest of the profile passed."""

    def __init__(self, problems: dict[str, list[str]]):
        self.problems = problems
        super().__init__("\n".join([m for ms in problems.values() for m in ms][:20]))


def schema_errors(instance: Any, schema: dict) -> list[str]:
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(e.path))
    return [f"{e.json_path}: {e.message}" for e in errors[:15]]


def ensure_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Input contains a non-finite number.")
    if isinstance(value, dict):
        for child in value.values():
            ensure_finite(child)
    elif isinstance(value, list):
        for child in value:
            ensure_finite(child)


def normalize_text(text: str) -> str:
    # No language correction, punctuation replacement, or Unicode normalization.
    return re.sub(r"<br\s*/?>", "\n", text.replace("\r\n", "\n").replace("\r", "\n"),
                  flags=re.IGNORECASE)


def prepare_user(user: dict) -> tuple[dict, dict]:
    """Assign neutral IDs to the complete supplied history; never read target data."""
    records: list[dict] = []
    index: dict[str, dict] = {}
    seen: set[str] = set()
    ordered = sorted(enumerate(user["reviews"]), key=lambda pair: (pair[1]["date"], pair[0]))
    for number, (original_index, source) in enumerate(ordered, 1):
        parsed_date = date.fromisoformat(source["date"])
        if parsed_date.isoformat() != source["date"]:
            raise ValidationFailure(f"{user['user_id']}: date must be YYYY-MM-DD.")
        review_id = f"R{number}"
        record = {
            "review_id": review_id, "date": source["date"],
            "parent_asin": source["parent_asin"], "rating": source["rating"],
            "review_title": normalize_text(source["review_title"]),
            "review_text": normalize_text(source["review_text"]),
            "product": copy.deepcopy(source["product"]),
        }
        # Keep distinct reviews, including prior reviews of the target ASIN.
        review_key = digest({k: record[k] for k in
                             ("date", "parent_asin", "rating", "review_title", "review_text")})
        if review_key in seen:
            raise ValidationFailure(f"{user['user_id']}: duplicate review at reviews[{original_index}].")
        seen.add(review_key)
        record["source_header"] = dump({
            "review_id": review_id, "date": record["date"], "parent_asin": record["parent_asin"],
            "rating": record["rating"], "product.price": record["product"]["price"],
        })
        index[review_id] = {"review_index": original_index, "date": record["date"],
                            "parent_asin": record["parent_asin"]}
        records.append(record)
    if not records:
        raise ValidationFailure(f"{user['user_id']}: no pre-T2 history.")
    return {"user_id": user["user_id"], "main_category": user["main_category"],
            "history": records}, index


def model_input(history: dict) -> dict:
    """Expose interpretation context, while retaining identity and statistics headers locally."""
    fields = ("review_id", "date", "parent_asin", "rating", "review_title", "review_text", "product")
    return {"main_category": history["main_category"],
            "history": [{key: record[key] for key in fields} for record in history["history"]]}


def make_body(history: dict, model: str, reasoning: str, max_output: int,
              system_prompt: str, user_template: str, api_schema: dict) -> dict:
    user_prompt = user_template.replace("{{HISTORY_JSON}}", dump(model_input(history), pretty=True))
    body = {
        "model": model,
        # text.format only constrains decoding; the model reads the schema from the system message.
        "input": [{"role": "system", "content": f"{system_prompt.rstrip()}\n{dump(api_schema, pretty=True)}"},
                  {"role": "user", "content": user_prompt}],
        "text": {"format": {"type": "json_schema", "name": "user_shopping_profile",
                             "strict": True, "schema": api_schema}},
        "max_output_tokens": max_output,
        "store": False,
        "truncation": "disabled",
    }
    if reasoning != "omit":
        body["reasoning"] = {"effort": reasoning}
    return body


def mismatch_detail(quote: str, record: dict) -> str:
    """Where a quote stops matching its record: the end of its longest matching start and what each side continues with."""
    wanted, quote_index = comparable(quote)
    best = None
    for text in (record["review_title"], record["review_text"]):
        flat, index = comparable(text)
        low, high = 0, len(wanted)
        while low < high:  # longest prefix of the quote found in this field
            mid = (low + high + 1) // 2
            if wanted[:mid] in flat:
                low = mid
            else:
                high = mid - 1
        if low and (best is None or low > best[0]):
            best = (low, text, index, flat.find(wanted[:low]))
    if best is None:
        return "The beginning of the quote does not appear in this record."
    n, text, index, at = best
    quote_end, source_end = quote_index[n - 1] + 1, index[at + n - 1] + 1
    return (f"The quote matches this record up to {quote[max(0, quote_end - 60):quote_end]!r}; then the quote continues "
            f"{quote[quote_end:quote_end + 60]!r} but the record continues {text[source_end:source_end + 60]!r}.")


def item_kind(path: str) -> str:
    """Schema definition name of the item at an entries() path."""
    if path.startswith("background_facts."):
        return "fact"
    return "usage" if path.startswith("usage_patterns[") else "preference"


def locate(profile: dict, path: str) -> tuple[list, int]:
    """The array that holds the item at an entries() path, and the item's index."""
    match = re.fullmatch(r"(?:(background_facts|product_preferences)\.)?([a-z_]+)\[(\d+)\]", path)
    if match is None:
        raise ValueError(f"Unknown item path: {path}")
    section, name, index = match.groups()
    return (profile[section][name] if section else profile[name]), int(index)


def item_repair_schema(profile_schema: dict, kind: str) -> dict:
    return {"type": "object",
            "properties": {
                "keep": {"type": "boolean",
                         "description": "false if no supported, in-scope claim remains in this item; it is then removed. Otherwise correct or narrow it without inventing evidence."},
                "item": {"$ref": f"#/$defs/{kind}"}},
            "required": ["keep", "item"], "additionalProperties": False,
            "$defs": profile_schema["$defs"]}


def fill(template: str, **values: str) -> str:
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], template)


def entries(profile: dict, *, include_statistics: bool = False) -> Iterable[tuple[str, dict]]:
    groups = FACT_GROUPS + (("history_statistics",) if include_statistics else ())
    for group in groups:
        for i, entry in enumerate(profile["background_facts"][group]):
            yield f"background_facts.{group}[{i}]", entry
    for i, entry in enumerate(profile["usage_patterns"]):
        yield f"usage_patterns[{i}]", entry
    for axis in AXES:
        for i, entry in enumerate(profile["product_preferences"][axis]):
            yield f"product_preferences.{axis}[{i}]", entry


def label_conflicts(profile: dict) -> list[dict]:
    """Identical quotes from one review that carry different evidence types. Recorded, not corrected."""
    seen: dict[tuple[str, str], dict[str, list[str]]] = {}
    for path, entry in entries(profile):
        for ev in entry["evidence"]["reviews"]:
            seen.setdefault((ev["review_id"], ev["quote"]), {}).setdefault(ev["evidence_type"], []).append(path)
    return [{"review_id": rid, "quote": quote, "labels": labels}
            for (rid, quote), labels in seen.items() if len(labels) > 1]


def statistic_facts(history: dict) -> list[dict]:
    """One metadata-price summary across the whole history; never a price preference."""
    priced = [r for r in history["history"] if r["product"]["price"] is not None]
    if not priced:
        return []
    prices = [Decimal(str(r["product"]["price"])) for r in priced]
    count = len(priced)
    text = (f"Non-missing product metadata prices linked to {count} reviews: "
            f"min {min(prices)}, max {max(prices)}, median {median(prices)}. "
            "Input price units are used as is; the currency is not confirmed in the input. "
            "Aggregated per review record; package sizes may differ. "
            "Do not interpret these as actual payments, prices at purchase time, unit prices, a current budget, or willingness to pay.")
    return [{"fact": text, "evidence": {
        "review_count": count,
        "reviews": [{"review_id": r["review_id"], "quote": r["source_header"],
                     "evidence_type": "metadata"} for r in priced]}}]


PUNCTUATION_VARIANTS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "…": "...",
})


def comparable(text: str) -> tuple[str, list[int]]:
    """Text without whitespace, with punctuation variants unified and letters lowercased,
    plus the source index of every kept character."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        for out in ch.translate(PUNCTUATION_VARIANTS).lower():
            chars.append(out)
            index.append(i)
    return "".join(chars), index


def source_passage(quote: str, record: dict) -> str | None:
    """The exact review_title/review_text passage that a quote copies, or None.

    Only whitespace, punctuation variants and letter case may differ; wording may not."""
    fields = (record["review_title"], record["review_text"])
    if quote.strip() and any(quote in text for text in fields):
        return quote
    wanted, _ = comparable(quote)
    if not wanted:
        return None
    for text in fields:
        flat, index = comparable(text)
        at = flat.find(wanted)
        if at >= 0:
            return text[index[at]:index[at + len(wanted) - 1] + 1]
    return None


def finalize(raw_profile: dict, history: dict, api_schema: dict, final_schema: dict) -> tuple[dict, dict]:
    """Validate model-owned content, ground its evidence, then add code-owned fields."""
    errors = schema_errors(raw_profile, api_schema)
    if errors:
        raise ValidationFailure("\n".join(errors))
    profile = copy.deepcopy(raw_profile)
    sources = {r["review_id"]: r for r in history["history"]}
    source_order = {r["review_id"]: i for i, r in enumerate(history["history"])}
    used: set[str] = set()
    adjustments: list[dict] = []
    restorations: list[dict] = []
    corrections: list[dict] = []
    problems: dict[str, list[str]] = {}
    for path, entry in entries(profile):
        evidence = entry["evidence"]
        if not evidence["reviews"]:
            raise ValidationFailure(f"{path}: cite at least one supporting review.")
        unique: dict[tuple[str, str], dict] = {}
        for ev in evidence["reviews"]:
            rid, quote = ev["review_id"], ev["quote"]
            passage = source_passage(quote, sources[rid]) if rid in sources else None
            others: list[str] = []
            if passage is None:
                # Verbatim text from another record: when exactly one record contains it, that record is its source.
                found = {other: p for other, record in sources.items()
                         if other != rid and (p := source_passage(quote, record)) is not None}
                if len(found) == 1:
                    (other, passage), = found.items()
                    corrections.append({"path": path, "model_review_id": rid, "review_id": other})
                    rid = ev["review_id"] = other
                others = sorted(found)
            if rid not in sources:
                problems.setdefault(path, []).append(f"{path}: unknown review_id={rid}")
                continue
            source = sources[rid]
            if passage is None:
                where = (f"The same text appears in {', '.join(others)}; cite the record it comes from."
                         if others else mismatch_detail(quote, source))
                problems.setdefault(path, []).append(
                    f"{path}: {rid} quote is not a continuous excerpt of review_title/review_text "
                    f"(compared ignoring only whitespace, punctuation style and letter case): {quote[:160]!r}. {where}")
            elif passage != quote:
                ev["quote"] = passage
                restorations.append({"path": path, "review_id": rid, "model_quote": quote, "source_quote": passage})
            unique[(rid, ev["quote"])] = ev
            used.add(rid)
        evidence["reviews"] = sorted(unique.values(),
                                     key=lambda ev: (source_order[ev["review_id"]], ev["quote"]))
        rids = {e["review_id"] for e in evidence["reviews"]}
        corrected = {"review_count": len(rids)}
        adjustments.append({"path": path, "computed_counts": corrected})
        evidence.update(corrected)
    if problems:
        raise SourceCheckFailure(problems)
    # Canonical order by earliest supporting review; no semantic rewriting.
    arrays = [profile["background_facts"][k] for k in FACT_GROUPS]
    arrays += [profile["usage_patterns"]]
    arrays += [profile["product_preferences"][a] for a in AXES]
    for arr in arrays:
        arr.sort(key=lambda e: min(source_order[v["review_id"]] for v in e["evidence"]["reviews"]))
    profile["user_id"] = history["user_id"]
    profile["main_category"] = history["main_category"]
    profile["background_facts"]["history_statistics"] = statistic_facts(history)
    errors = schema_errors(profile, final_schema)
    if errors:
        raise ValidationFailure("Postprocessing schema error: " + "\n".join(errors))
    report = {
        "status": "schema_and_source_checks_passed",
        "semantic_validity": "not_automatically_verified",
        "history_records": len(history["history"]),
        "records_cited_in_semantic_entries": len(used),
        "uncited_review_ids": [r["review_id"] for r in history["history"] if r["review_id"] not in used],
        "note": "An uncited review is not necessarily an omission error. Conversely, a citation does not guarantee that the interpretation is valid.",
        "computed_count_updates": adjustments,
        "quote_restorations": restorations,
        "review_id_corrections": corrections,
        "label_conflicts": label_conflicts(profile),
    }
    return profile, report


async def generate(run, entry: dict, transport) -> dict:
    """Generate one grounded profile; a completed profile is a resumable boundary."""
    history, source_index = prepare_user(run.input(entry, 'history'))
    config = run.config['llm']
    request = make_body(history, config['model'], config['reasoning'], config['max_output_tokens'],
                        run.prompt('profile'), run.prompt('profile_input'), run.schema('profile_api'))
    cache_input = {'request': request, 'schema': run.schema('profile'), 'source_index': source_index,
                   'user_id': history['user_id']}
    cached = run.cached(entry['key'], 'profile', cache_input)
    if cached is not None:
        return cached
    profile = None
    pending = None
    repair_log = []
    base = copy.deepcopy(request)
    for round_no in range(run.config['generation']['profile_repairs'] + 1):
        prior = None
        try:
            if pending:
                repaired = copy.deepcopy(profile)
                removals = []
                for path, errors in pending.items():
                    array, index = locate(repaired, path)
                    schema = item_repair_schema(run.schema('profile_api'), item_kind(path))
                    item_request = copy.deepcopy(base)
                    item_request['input'] += [
                        {'role': 'assistant', 'content': dump(profile, pretty=True)},
                        {'role': 'user', 'content': fill(run.prompt('profile_item_repair'),
                            PATH=path, ITEM_JSON=dump(array[index], pretty=True),
                            ERRORS_JSON=dump({'validation_errors': errors}, pretty=True),
                            SCHEMA_JSON=dump(schema, pretty=True))}]
                    item_request['text']['format'] = {'type': 'json_schema', 'name': 'profile_item_repair',
                                                      'strict': True, 'schema': schema}
                    fixed = await checked_json(transport, entry['key'], 'profile_item_repair',
                                               item_request, lambda value: [], repairs=0)
                    repair_log.append({'round': round_no, 'path': path, 'kept': fixed['keep'], 'errors': errors})
                    if fixed['keep']:
                        array[index] = fixed['item']
                    else:
                        removals.append((array, index))
                for array, index in sorted(removals, key=lambda pair: pair[1], reverse=True):
                    del array[index]
                profile, pending = repaired, None
            elif profile is None:
                prior = output_text(await transport.call(entry['key'], 'profile', request))
                profile = json.loads(prior)
                ensure_finite(profile)
            final, report = finalize(profile, history, run.schema('profile_api'), run.schema('profile'))
            value = {'profile': final, 'checks': report, 'source_index': source_index, 'repairs': repair_log}
            return run.save(entry['key'], 'profile', cache_input, value)
        except SourceCheckFailure as error:
            if round_no == run.config['generation']['profile_repairs']:
                raise
            pending = error.problems
        except (ValidationFailure, json.JSONDecodeError) as error:
            if round_no == run.config['generation']['profile_repairs']:
                raise
            prior = prior if prior is not None else dump(profile, pretty=True)
            request = copy.deepcopy(base)
            request['input'] += [{'role': 'assistant', 'content': prior}, {'role': 'user',
                'content': run.prompt('profile_repair').replace('{{ERRORS_JSON}}',
                            dump({'validation_errors': str(error)}, pretty=True))}]
            profile, pending = None, None
    raise AssertionError('Unreachable')
