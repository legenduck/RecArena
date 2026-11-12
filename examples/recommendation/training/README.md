# Train BPR or LightGCN

This example converts fixed interactions, selects a training duration on validation data, refits the model and exports inference factors. BPR is the default; LightGCN is the other supported model. A platform database or recommendation service is not needed during training.

## Convert prepared interactions

First complete [common data preparation](../../data/README.md). From the repository root:

```bash
uv run --frozen --project examples python examples/recommendation/training/prepare_interactions.py \
  --prepared artifacts/amazon/Grocery_and_Gourmet_Food/prepared.json \
  --dataset Amazon_Grocery_and_Gourmet_Food --output artifacts/interactions
```

Conversion uses the [shared example environment](../../README.md#shared-example-environment) without training dependencies. It writes `Amazon_Grocery_and_Gourmet_Food.{train,valid,test,trainval}.inter` under the new dataset directory and `conversion.json` with source partitions, T1/T2 and counts.

General-model columns are `user_id:token`, `item_id:token` (parent ASIN), `rating:float`, `timestamp:float` (milliseconds). Trainval combines train and validation in time order. Cold users/items and low ratings remain; no split or cutoff is recalculated. Alternatively, `--split-dir` reads the three `review_{train,valid,test}.parquet` files directly.

Optional `--format sequential --max-len 50` creates user/history/target/timestamp inputs for sequential benchmarks. Each target uses that user's preceding rows, including preceding validation/test interactions, and keeps its split; the first row without history is omitted. This format is separate from the general-model files used below. Use a new dataset name or output directory for each conversion.

## Enable training

```bash
uv sync --frozen --project examples --extra training
```

This adds RecBole and PyTorch 2.5.1 with CUDA 12.1 to `examples/.venv`. A compatible NVIDIA driver and accessible GPU are required. Select a GPU with `CUDA_VISIBLE_DEVICES`; a GPU request fails when CUDA is unavailable.

For CPU execution, install `--extra training-cpu` instead, use that extra on `uv run`, and pass a YAML configuration containing:

```yaml
training:
  use_gpu: false
```

The extras are mutually exclusive. Retain other extras you use, such as `--extra scenarios`, in sync/run commands. The optional [training Compose service](compose.yaml) requires NVIDIA Container Toolkit on its host and uses GPU 0 unless `RECARENA_TRAINING_GPU` is set.

## Train and export

Use the catalog/history IDs chosen for the corresponding platform data:

```bash
uv run --frozen --project examples --extra training python -m recarena_training.pipeline \
  --data artifacts/interactions/Amazon_Grocery_and_Gourmet_Food \
  --catalog my-catalog-v1 --history my-history-v1 \
  --output artifacts/models/bpr
```

Use `--model LightGCN` and a new output directory for LightGCN. The default `--train-split auto` performs:

1. Train on `train.inter`, selecting the best epoch count with `valid.inter`.
2. Initialize a new model and optimizer; combine the exact train/validation input copies and train for the selected count.
3. Evaluate that refitted model on test, then export it for serving.

The count is `best_epoch + 1` because the stored epoch index starts at zero. Test never selects the duration. Refit has no validation early stopping; prepared files, including `trainval.inter`, remain unchanged.

## Settings

Pass `--config configs/local/training.yaml` with the values to change:

```yaml
model: BPR
training:
  epochs: 300
  embedding_size: 64
  train_batch_size: 2048
  learning_rate: 0.001
  stopping_step: 10
```

`epochs` caps the selection stage; the refit count is automatic. `--model` overrides the YAML model. LightGCN also accepts `n_layers` and `reg_weight`. Prepared input fields and partition rules cannot be overridden by tuning settings.

For manual experiments, `--train-split train` exports the validation-selected model, while `--train-split trainval` uses a prepared trainval file and requires an explicit fixed epoch count. Neither flag is needed for the default procedure. Conversion resource options are `--threads` and `--memory-limit`.

## Outputs and serving

| Output | Contents |
|---|---|
| `selection/` | Selection-stage inputs, checkpoint and validation result |
| `training/` | Final training inputs, configuration, checkpoint and reports |
| `serving/manifest.json` | Inference artifact identity and file inventory |
| `serving/` | NumPy factors, user/item mappings and model metadata |
| `result.json` | Successful job and serving artifact IDs |
| `failed.json` | Failure information if an initialized job fails |

Reports separate selection validation metrics from final test metrics. Training history represents train+validation, with timestamps converted to seconds. Empty partitions are errors. LightGCN exports graph-propagated vectors; exported dot products are checked against model predictions before completion.

Build the [example server's index](../ranker/README.md#prepare-bm25-inputs), then generate a provider configuration:

```bash
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.build.profiles \
  --training-job artifacts/models/bpr --index artifacts/example/index/manifest.json \
  --policy-id personalization --output configs/local/personalization-server.json
```

The policy retrieves BM25 candidates and reranks them by model dot product. It has no BM25 blend weight. Ties use BM25 then product ID; untrained items follow trained items in BM25 order. Use `--config existing-server.json` to preserve other policies, with distinct IDs for BPR and LightGCN. Follow the ranker guide to [serve this configuration](../ranker/README.md#serve-with-compose).

## Completion and retries

A training run needs a new output directory; it does not resume an interrupted job. Retain failure records and rerun into a new directory. Inspect a completed export without training again:

```bash
uv run --frozen --project examples --extra training python -m recarena_training.export \
  --training-job artifacts/models/bpr
```
