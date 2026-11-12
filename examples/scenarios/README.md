# Prepare research scenarios

This example creates user histories, research profiles, scenarios, preference checklists and shopping requests from common Amazon data. **Alternative Selection (AS)** asks for a general product type; **Target Finding, attribute-specific (TFA)** describes a target through its brand and selected features. Generation needs neither a running platform nor a recommendation model.

## Inputs

Complete [common data preparation](../data/README.md). Its `prepared.json` identifies fixed T2/partitions and the original metadata/reviews. Keep those originals accessible during preparation: histories can include products outside the platform catalog.

From the repository root, install the scenario extra and copy its configuration:

```bash
uv sync --frozen --project examples --extra scenarios
mkdir -p configs/local
cp examples/scenarios/configs/default.yaml configs/local/scenarios.yaml
```

Retain any other extras you use in sync/run commands; see the [shared environment](../README.md#shared-example-environment).

## Prepare and generate

Edit the copied configuration, then prepare a frozen run without model calls:

```bash
uv run --frozen --project examples --extra scenarios recarena-scenarios prepare \
  --prepared artifacts/amazon/Grocery_and_Gourmet_Food/prepared.json \
  --config configs/local/scenarios.yaml --output outputs/scenarios/grocery-run
```

Inspect `records/run.json` for the selected users, inputs and settings. If original files have moved, provide their new paths with `--metadata` and `--reviews`.

Set `OPENAI_API_KEY` in your shell or secret manager, then generate:

```bash
uv run --frozen --project examples --extra scenarios recarena-scenarios generate \
  --run outputs/scenarios/grocery-run
```

`generate` makes paid model calls. It creates a grounded profile for each selected user, followed by a scenario, checklist and the requested AS/TFA text.

## Selection and settings

| Configuration | Default | Meaning |
|---|---|---|
| `selection.min_reviews` | 50 | Minimum original pre-T2 reviews after deduplication |
| `selection.min_category_reviews` | 10 | Minimum reviews in the user's main category path |
| `selection.target_min_rating` | 4 | Minimum target test-review rating |
| `selection.allow_new_targets` | true | Permit a target absent from train+validation when no warm target is available |
| `selection.sample_size`, `seed` | 100, 42 | Uniform user sample without replacement |
| `generation.intents` | `[as]` | `[as]`, `[tf]` (TFA only), or `[as, tf]` |
| `generation.concurrency` | 8 | Concurrent user generation jobs |
| `llm.model`, `reasoning` | `gpt-6-luna`, `xhigh` | Explicit model and reasoning setting |
| `llm.max_output_tokens` | 128000 | Per-call output limit |

The chosen model must be available to your API account. Configuration also controls memory/threads, timeouts, network retries and semantic repairs; see [default.yaml](configs/default.yaml).

User and target selection follows these rules:

1. Keep users present in train+validation whose deduplicated original reviews strictly before T2 meet the required count.
2. Deduplicate each user/product pair by earliest timestamp, then descending helpful votes, descending purchase verification, ASIN, rating, title and text.
3. Choose the full raw category path with the most reviews and at least the configured minimum. Ties use the display string, then the path array. Empty paths cannot be selected.
4. Choose a qualifying test purchase in exactly that path, preferring products present in train+validation, then timestamp and product ID.
5. Uniformly sample the eligible users using the seed, and freeze the selected list before generation.

All reviews are treated equally. Other category paths count toward eligibility but are excluded from the main-path profile history. Matching uses the entire path array. History is one `reviews` array with chronological IDs `R1`, `R2`, etc.; no later candidate-product scoring or user reselection occurs.

## Generation rules and prompts

| Call | Model input | Result |
|---|---|---|
| Profile | Main-path reviews, dates and product records | Background facts, usage patterns and preferences with quoted evidence |
| Scenario | Profile and target listing/price, excluding the target review | Product type, situation and budget |
| Checklist | Profile without quotes, category and situation; no target listing | Preference criteria and accounting for unused profile items |
| AS request | Product type, situation and budget | A request without supplied preferences or a target brand |
| TFA request | Scenario and target listing, excluding target price/review | Request text, brand and two or three selected features |

Profile claims must be grounded in review text. The model receives no internal user ID; code attaches identity/category, counts distinct evidence reviews and computes history statistics. Schema and quote checks validate structure and grounding, not semantic correctness. Unsupported items may be repaired or excluded, with the decision recorded.

AS and TFA share [checklist.md](recarena_scenarios/prompts/checklist.md). Code adds one request-budget criterion when the scenario supplies a budget, then numbers all criteria; profile price preferences remain separate. The scenario prompt requests a range containing the target price. An AS range outside it is accepted; a TF range outside it triggers correction.

The [prompt directory](recarena_scenarios/prompts/) holds profile generation/input/two repair prompts, scenario, checklist and AS/TFA request prompts. Edit these before preparing a new run. Prompts and schemas are frozen into that run with exact hashes.

## Outputs

```text
outputs/scenarios/grocery-run/
├── dataset/                 # published when every selected user/intent completes
│   ├── manifest.json        # format, settings, sources, selected users and hashes
│   ├── histories.jsonl      # main-path reviews; excludes targets
│   ├── profiles.jsonl       # research profiles and grounding records
│   ├── tasks.jsonl          # target, scenario, checklist and canonical request
│   └── requests.jsonl       # task_id and request, projected from tasks
├── work/                    # candidate audit, frozen inputs and successful stages
└── records/                 # run settings, prompts/schemas, status and raw attempts
```

Each task is `AS` or `TF_attribute_specific`. TFA request conditions are stored in `tf.brand`, `tf.attribute_features` and `scenario.product_type`. AS has no QC payload. [Product judging](../judging/README.md) reads `tasks.jsonl` after products have been selected.

Give the agent its request from `requests.jsonl`. Research profiles, targets and checklists remain evaluation inputs. `histories.jsonl` can feed an agent-specific memory converter; no agent memory format or runner is created here. Outputs belong under Git-ignored `outputs/`.

## Resume and completion

Repeat `generate --run` to resume. Successful stages are reused; failed users are neither replaced nor dropped. One generator process owns a run. A complete dataset is published only after all selected users and intents finish.

Prepare a new directory when changing sample, settings, prompts or code. Runs use `recarena-scenario-run-v3` and datasets use `recarena-scenario-dataset-v3`; resuming older formats requires their original code. Prepared runs contain all generation inputs; original large files are identified by path/size/mtime, while frozen inputs and prompts have content hashes.

Raw responses and provided usage are recorded before parsing. Network retries and semantic repairs are separate. An interrupted model call can have unknown completion/usage and a retry can incur another charge. The API key is read from the environment and is not saved.
