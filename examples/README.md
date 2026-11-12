# Optional research examples

These examples prepare data, recommendations and research tasks for RecArena. The platform installs independently and accepts other implementations through its data and HTTP contracts.

## Workflow

Start with [data preparation](data/README.md): download one Amazon category, apply the product/review rules and fix the time split. Its `prepared.json` feeds three independent branches:

```text
Amazon originals → common preparation → prepared.json
  ├─ platform conversion → catalog/reviews/history → platform import
  ├─ interaction conversion → BPR or LightGCN → serving factors
  └─ user sampling → profiles/scenarios/checklists → requests and research tasks
```

| Task | Guide | Result |
|---|---|---|
| Download and prepare a category | [data/](data/README.md) | Common Parquet files and fixed T1/T2 |
| Prepare the shop's data | [Platform conversion](data/README.md#prepare-platform-data) | Importable catalog package |
| Train a recommendation model | [recommendation/training/](recommendation/training/README.md) | Inference factors and ID mappings |
| Build an index and run recommendations | [recommendation/ranker/](recommendation/ranker/README.md) | A service the platform can discover |
| Prepare shopping tasks | [scenarios/](scenarios/README.md) | Histories, profiles, scenarios, checklists and requests |
| Judge selected products | [judging/](judging/README.md) | Preference Satisfaction, Query Compliance and Target Hit |
| Issue or end a session | [create_session.py](create_session.py) | Session URL or termination result; use `--help` |

For a first shop, prepare the common data and platform package, then build the ranker's index directly from prepared metadata. Run `./recarena init`, start that provider, and return to the [platform guide](../README.md#start-the-platform) to start/import/register/issue a session. BM25 needs no model training. Keep catalog/history IDs consistent across the package, model and policy.

Scenario preparation and judging also run without a live platform. To run agents, supply the prepared request and your agent's memory, obtain a session URL, and collect selected product IDs for judging. Agent-specific memory conversion and execution are not implemented by these examples.

## Shared example environment

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository root:

```bash
uv sync --frozen --project examples
```

This creates `examples/.venv` with Python 3.11.17 (downloaded if needed) and data dependencies. Add the extras for the tasks you use:

| Extra | Adds |
|---|---|
| `--extra training` | RecBole and CUDA 12.1 PyTorch; GPU training is the default |
| `--extra training-cpu` | RecBole and CPU PyTorch; also set `training.use_gpu: false` |
| `--extra scenarios` | Profile/task generation and its LLM client |
| `--extra judging` | Product judging and its LLM client |

For example, `uv sync --frozen --project examples --extra scenarios --extra judging` installs both. Keep the same selected extras on subsequent `uv run` commands. The two training extras are mutually exclusive; a GPU request fails if CUDA is unavailable. The default installation includes neither PyTorch nor test packages.

These packages share `examples/uv.lock`. The recommendation server uses its own Python 3.12 environment and Java 21; see its installation guide. The platform has a separate environment. Scenario generation and judging share the internal `llm/` package for API transport and records; it has no standalone command.
