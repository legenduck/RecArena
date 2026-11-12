# Run the example recommendation server

This optional provider builds search/scoring artifacts and serves configured policies through the [platform HTTP contract](../../../docs/RECOMMENDATION_API.md). BM25 works without a trained model; BPR and LightGCN use exported inference factors. All commands run from the repository root.

## Inputs and environment

Use prepared product metadata or a platform `CatalogProducts` export. Install [uv](../../README.md#shared-example-environment) and Java 21, then create this provider's separate Python 3.12 environment:

```bash
uv sync --frozen --project examples/recommendation/ranker
```

The optional `metadata` group adds the Amazon adapter. Pyserini 2.4 retrieves version-pinned index metadata when initializing, so index preparation and serving startup need internet access. The search index itself is built from your product corpus.

## Prepare BM25 inputs

For a first shop, use [common prepared metadata](../../data/README.md#prepare-common-data); the platform need not be running:

```bash
uv run --frozen --project examples/recommendation/ranker --group metadata python -m recarena_ranker.build.from_metadata \
  --metadata artifacts/amazon/Grocery_and_Gourmet_Food/meta_final.parquet \
  --catalog my-catalog-v1 --output artifacts/example/metadata-corpus
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.build.index \
  --corpus artifacts/example/metadata-corpus/corpus.json --output artifacts/example/index
```

For an existing platform catalog, create the corpus instead with:

```bash
./recarena --docker sources products --catalog my-catalog-v1 --output outputs/products.json
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.build.corpus \
  --products outputs/products.json --output artifacts/example/corpus.json
```

Use that corpus path in the same index command. Both input paths index product titles, features, descriptions, categories and scalar attributes for purchasable products. The platform's catalog export supplies the original registered fields; this provider chooses which fields enter search. Changing that selection requires a new corpus and index, even when the platform catalog is unchanged.

## Configure policies

Run `./recarena init` to create private configuration directories and credentials if needed. Save this as `configs/local/example-ranker.json`:

```json
{"indices": ["artifacts/example/index/manifest.json"], "policies": []}
```

Copy the [BM25 policy example](configs/relevance-policy.json):

```bash
cp examples/recommendation/ranker/configs/relevance-policy.json configs/local/my-policy.json
```

Set `catalog_snapshot_id` to the catalog label used above and `index_artifact_id` to `artifact_id` in the index manifest. Choose a `policy_id` and display `name`, then generate the versioned configuration:

```bash
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.build.profiles \
  --config configs/local/example-ranker.json --policy-file configs/local/my-policy.json \
  --output configs/local/example-ranker-ready.json
```

For BPR or LightGCN, follow [training and connection](../training/README.md#outputs-and-serving). Supply `--config` when adding a policy to an existing server configuration. The server serves only declared policies; requests choose one policy/version. New settings require a new version and platform environment; keep versions needed by active sessions available.

For diversity, prepare TF-IDF features from the same product corpus:

```bash
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.build.features tfidf \
  --input artifacts/example/metadata-corpus/corpus.json --output artifacts/example/tfidf
```

Add its manifest path to the server config's `tfidf` list. Copy the [diversity policy example](configs/diversity-policy.json), fill in its catalog, index and TF-IDF artifact IDs, then use the same `build.profiles` command. Greedy MMR defaults to `0.7 × min-max-normalized BM25 − 0.3 × maximum TF-IDF cosine similarity to already selected products`. It requires no BPR model or user-specific scores. Explicit settings in previously generated policies remain unchanged; generate a new policy version to use different weights.

## Serve with Compose

For the BM25 or trained-model configuration above, copy verified serving artifacts into the runtime mount and convert their paths. Use `configs/local/personalization-server.json` as the input argument for a trained-model configuration:

```bash
uv run --frozen --project examples/recommendation/ranker python - configs/local/example-ranker-ready.json <<'PYTHON'
import json, sys
from pathlib import Path
from recarena_ranker.build.stage import stage
config = json.loads(Path(sys.argv[1]).read_text())
root = Path('artifacts/runtime').resolve()
for key in ('indices', 'bpr', 'cf', 'review_timestamps', 'tfidf'):
    if key in config:
        config[key] = ['/app/artifacts/runtime/' + stage(p, root).relative_to(root).as_posix()
                       for p in config[key]]
with Path('configs/local/docker/ranker.json').open('x') as stream:
    json.dump(config, stream, indent=2)
PYTHON
mkdir -p outputs/ranker-state
```

This creates a new config; if one already exists, preserve it before replacing it. Set `RECARENA_RANKER_URL` to `http://ranking-api:8011` in `configs/local/docker/settings.json`. Run `./recarena init` again to refresh `compose.env`, then build and start the provider:

```bash
docker compose --env-file configs/local/docker/compose.env \
  -f compose.yaml -f examples/recommendation/ranker/compose.yaml build ranking-api ranking-worker
docker compose --env-file configs/local/docker/compose.env \
  -f compose.yaml -f examples/recommendation/ranker/compose.yaml up -d ranking-api
```

Workers read the staged files and receive the platform's internal credential through a Compose secret. After this provider is ready, follow the [platform guide](../../../README.md#start-the-platform) to start the site, import the matching catalog and [publish an environment](../../../docs/RECOMMENDATION_API.md#publish-a-platform-environment).

Set `RECARENA_RANKER_REPLICAS` in `settings.json`, refresh with `./recarena init`, and repeat `up -d ranking-api` to change replica count. The default is one; the proxy routes requests by active connections. This changes serving capacity without training or rebuilding data. Stop only the provider with:

```bash
docker compose --env-file configs/local/docker/compose.env \
  -f compose.yaml -f examples/recommendation/ranker/compose.yaml stop ranking-api ranking-worker
```

## Native serving

For a platform that can reach the native host/port, use the configuration's host paths directly. This localhost example is for services on the same host:

```bash
export RECARENA_INTERNAL_TOKEN="$(cat configs/local/docker/internal_token.secret)"
uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.serve \
  --config configs/local/example-ranker-ready.json --host 127.0.0.1 --port 8011
```

`--workers` selects native serving processes. `--help` lists candidate count, popularity-window and weight settings for applicable policies. A pure CF reranking policy from the training example does not accept a BM25 blend weight. Pop, TF-IDF and profile artifact preparation are available in the build modules; their manifests must be included in the chosen server config.

## Outputs and reuse

Index output has `manifest.json`, corpus documents, index configuration and Lucene files. Policy generation writes a new server JSON and derives versions from its contents. Artifact IDs identify immutable prepared data; use new output paths for new builds/configurations. Reuse a verified index or model without preparing it again, and restart the provider after selecting a different config. Model training never runs during an HTTP recommendation request.
