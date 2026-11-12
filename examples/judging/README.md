# Judge selected products

This example evaluates selected products against prepared research tasks. **TFA uses Preference Satisfaction (PS), Query Compliance (QC) and exact-parent-ASIN Target Hit; AS uses PS only.** It runs independently of the platform and agent. A supplied selection does not establish that a purchase was confirmed.

## Inputs

Product judgments use three inputs:

- `dataset/tasks.jsonl` from [scenario preparation](../scenarios/README.md).
- The same category's common [prepared.json](../data/README.md#prepare-common-data).
- A selection JSONL, with one row per chosen product:

```json
{"choice_id":"trial-001-product-1","task_id":"TASK_ID_FROM_TASKS_JSONL","parent_asin":"CHOSEN_PARENT_ASIN"}
```

Use a unique `choice_id` for each choice, including repeated tasks/products across trials. Extra metadata is retained in output but is not sent to the model. Convert agent-specific logs to these records outside the evaluator.

For aggregate TF Target Hit, also supply an execution-results JSONL with **one row per evaluated execution, including executions without a purchase**:

```json
{"rollout_id":"trial-001","task_id":"TASK_ID_FROM_TASKS_JSONL","purchased_parent_asins":["PURCHASED_PARENT_ASIN"]}
{"rollout_id":"trial-002","task_id":"TASK_ID_FROM_TASKS_JSONL","purchased_parent_asins":[]}
```

Use confirmed purchase records; a viewed, selected or carted product is not a purchase. `[]` explicitly records no purchase. Repetitions use different `rollout_id` values even for the same task; duplicate execution IDs are rejected. Supply the complete evaluated cohort for the condition being reported, not just successful executions. Without this input, aggregate Hit is null. An empty selection file is allowed when computing only Hit from execution results.

## Prepare and judge

Run from the repository root, retaining other extras you use:

```bash
uv sync --frozen --project examples --extra judging
mkdir -p configs/local
cp examples/judging/configs/default.yaml configs/local/judging.yaml
uv run --frozen --project examples --extra judging recarena-judge prepare \
  --tasks outputs/scenarios/grocery-run/dataset/tasks.jsonl \
  --selections outputs/experiment/selections.jsonl \
  --rollouts outputs/experiment/rollouts.jsonl \
  --prepared artifacts/amazon/Grocery_and_Gourmet_Food/prepared.json \
  --config configs/local/judging.yaml --output outputs/judging/grocery-run
```

`prepare` makes no model calls. It freezes tasks, choices, supplied execution results, catalog-based page inputs, settings and the prompt. Page fields come from prepared metadata; rating/count use finite 1–5 pre-core deduplicated reviews strictly before T2, with the mean rounded to one decimal. These are reconstructed listing inputs, not browser captures. Review bodies are excluded.

Set `OPENAI_API_KEY` through your shell or secret manager, then run paid judgments:

```bash
uv run --frozen --project examples --extra judging recarena-judge run \
  --run outputs/judging/grocery-run
```

## Settings and judgment rules

Defaults in [configs/default.yaml](configs/default.yaml) are `gpt-6-luna`, xhigh reasoning, 16,000 output tokens and up to 200 concurrent calls. Adjust concurrency, model, reasoning, output limit, timeout or retries in the copied file before preparation. The model must be available to your API account.

PS and QC share [attribute_judge_system.md](recarena_judging/prompts/attribute_judge_system.md). Each call receives one `PAGE` and one `CRITERION`, without the task, target, profile, other criteria or a PS/QC label. Verdicts include evidence and are `met`, `not_met` (contradicted or absent), or `not_applicable`.

| Score | Definition |
|---|---|
| PS | Saved preference checklist excluding request-budget criteria; `met / total criteria` |
| QC, TFA only | Brand, product type, saved features and saved request-budget criteria; the same ratio |
| `qc_all_met`, TFA only | Whether every QC criterion is met |
| Target Hit, TFA only | Executions purchasing the exact target `parent_asin` divided by all evaluated TF executions; no LLM comparison |

Request-budget criteria are identified by `axis: price` and `origin: request`. They remain in the generated task checklist and frozen task input. Judging excludes them from PS for both AS and TFA, and uses their saved text unchanged as TFA QC criteria. AS has no QC and does not judge the request budget. History-derived price preferences remain in PS. No budget is invented when the checklist has none; QC does not add catalog-path or situation conditions.

For each score, every assigned criterion stays in the denominator. Only `met` contributes 1; `not_met` and `not_applicable` contribute 0. Three met, one not met and one not applicable give `3 / 5 = 0.6`. All-not-applicable criteria give 0; an empty criterion list gives null. Raw verdicts and not-applicable counts are retained. PS per-axis scores and QC per-condition summaries use the same rule.

For Target Hit, no purchase or purchasing only other products contributes 0. A purchase containing the target contributes 1, even if several products or units were bought. For example, 60 target purchases, 20 other purchases and 20 executions without a purchase give `60 / 100 = 0.6`. Per-choice `scores.hit` retains the chosen/target ASIN comparison; it does not establish a purchase and is not used as the aggregate numerator.

## Outputs and interpretation

```text
outputs/judging/grocery-run/
├── dataset/              # published when every choice completes
│   ├── manifest.json     # input/config/prompt/code identity and output hashes
│   ├── results.jsonl     # per-choice judgments, evidence and scores
│   ├── rollouts.jsonl    # evaluated executions used for the Hit denominator
│   └── summary.json      # completed summary
├── summary.json          # current summary, including failed/unfinished choices
├── records/              # frozen settings/prompt/schema, status and raw attempts
└── work/                 # frozen inputs and reusable successful judgments
```

PS/QC means cover completed choices with available scores. Numerators, denominators, unavailable ratios and selected/completed/failed/unfinished counts are explicit. Hit covers all supplied evaluated TFA executions regardless of LLM completion, and reports purchase/no-purchase counts. It can be computed by `summarize` immediately after preparation without an API key. A partial judgment summary has `final: false`; a failed LLM judgment is not inserted as a zero PS/QC score or a negative verdict.

To recompute summaries without an API key or new model calls:

```bash
uv run --frozen --project examples --extra judging recarena-judge summarize \
  --run outputs/judging/grocery-run
```

## Resume and completion

Repeat `run --run` to reuse completed choices and successful criterion calls. Changed inputs, settings, prompts or code require a new run. Frozen page inputs have content hashes; large source files are identified by path/size/mtime.

Raw attempts and supplied usage are retained, but API keys are not saved. An interrupted call can have unknown completion/usage and a retry may incur another charge. Network retry and correction limits are separate settings. Keep all output under Git-ignored `outputs/`.
