# Prepare Amazon data

Prepare one Amazon Reviews 2023 category through a fixed time split, then convert it for the platform, training or scenarios. Use the [shared example environment](../README.md#shared-example-environment); this stage needs neither training dependencies nor a running service. All commands below run from the repository root.

## Download originals

Use existing raw files, or download metadata and reviews from the [official dataset source](https://amazon-reviews-2023.github.io/):

```bash
uv run --frozen --project examples python -m recarena_data.download \
  --category Grocery_and_Gourmet_Food --output artifacts/amazon/raw
```

The command requires `curl`. `--print-urls` prints the two source URLs. Completed files are reused and `.part` downloads resume. Product images and precomputed benchmark splits are not downloaded.

## Prepare common data

```bash
uv run --frozen --project examples python -m recarena_data.prepare \
  --category Grocery_and_Gourmet_Food \
  --metadata artifacts/amazon/raw/meta_categories/meta_Grocery_and_Gourmet_Food.jsonl.gz \
  --reviews artifacts/amazon/raw/review_categories/Grocery_and_Gourmet_Food.jsonl.gz \
  --output artifacts/amazon/Grocery_and_Gourmet_Food \
  --threads 8 --memory-limit 8GB
```

The selection rules are:

1. Keep metadata with a numeric JSON price and at least one non-null `hi_res`, `large` or `thumb` field. This checks metadata, not image availability.
2. Keep those products' reviews with all ratings, ordered by timestamp, user and parent product.
3. Keep the earliest review for each user/product pair; timestamp ties use ASIN, then review text.
4. Repeatedly remove users/products with fewer than five interactions, counting both sides before each removal pass.
5. Compute category-specific `quantile_disc` boundaries at 80% and 90%: train is before T1, validation is `[T1, T2)`, and test is T2 onward.

`--ratios` sets different split shares. Equal timestamps stay together, so actual shares can differ. `--threads` and `--memory-limit` control DuckDB resources. An empty 5-core or missing timestamps cannot produce cutoffs; an empty split from a boundary tie is reported without moving rows.

| Common output | Meaning |
|---|---|
| `prepared.json` | Original paths, intermediate paths, counts, settings and fixed T1/T2 |
| `meta_final.parquet` | Products surviving 5-core |
| `review_deduped.parquet` | Deduplicated reviews before 5-core |
| `review_5core.parquet` | Reviews surviving 5-core |
| `splits/review_{train,valid,test}.parquet` | Fixed partitions |
| Other intermediate Parquet files | Filtered metadata/reviews and sorted reviews |

Keep the original files for scenario preparation. The same `prepared.json` independently feeds [training conversion](../recommendation/training/README.md#convert-prepared-interactions), [platform conversion](#prepare-platform-data) and [scenario preparation](../scenarios/README.md).

## Prepare platform data

Choose the IDs you will also use in the matching recommendation configuration:

```bash
uv run --frozen --project examples python -m recarena_data.platform \
  --prepared artifacts/amazon/Grocery_and_Gourmet_Food/prepared.json \
  --catalog my-catalog-v1 --review my-reviews-v1 --history my-history-v1 \
  --output artifacts/platform/Grocery_and_Gourmet_Food \
  --threads 8 --memory-limit 8GB
```

| Platform input | Selection |
|---|---|
| Products | `meta_final.parquet` |
| Public reviews | Pre-core deduplicated reviews of those products, strictly before T2, including reviewers removed from 5-core |
| Research user history | 5-core train + validation |

Public reviews retain finite ratings from 1 to 5; unsupported ratings are excluded and counted in `platform.json.review_selection`. Product ratings/counts use that public-review population. A product with no public reviews has rating null and count zero. Public reviewers outside the research history are not added as research users. This conversion reuses T2 and the item set without training or contacting a service.

The output contains `review_platform.parquet`, `catalog/` and `platform.json` (selection counts, T2 and history fingerprint). Once the [platform is running](../../README.md#start-the-platform), import the package:

```bash
./recarena --docker data import \
  --bundle artifacts/platform/Grocery_and_Gourmet_Food/catalog/manifest.json
```

The import connects to PostgreSQL; conversion only creates files. To build the example recommendation index before the platform starts, use the [prepared-metadata route](../recommendation/ranker/README.md#prepare-bm25-inputs).

## Preselected input files

For independently selected files, use the adapter directly:

```bash
uv run --frozen --project examples python -m recarena_data.provided_catalog \
  --metadata /path/to/meta_final.parquet --reviews /path/to/review_platform.parquet \
  --history-parquet /path/to/review_train.parquet \
  --history-parquet /path/to/review_valid.parquet \
  --catalog my-catalog-v1 --review my-reviews-v1 --history my-history-v1 \
  --output artifacts/my-catalog
```

By default, each metadata image contributes its `large` URL, falling back to `hi_res` then `thumb`, in source order. Browsers load these URLs directly. Other data sources can supply HTTP(S) `image_urls` through the platform format. A variant without images uses its product's images; missing images use a placeholder.

## Optional self-hosted images

Before creating a new catalog package, download and register images explicitly:

```bash
uv run --frozen --project examples python -m recarena_data.provided_images \
  --download --metadata artifacts/amazon/Grocery_and_Gourmet_Food/meta_final.parquet \
  --root artifacts/my-images --source-key my-images \
  --catalog my-catalog-v1 --output artifacts/my-image-assets --workers 8
```

Both destination directories must be new. To register an existing collection, replace `--download` with `--source-manifest /path/to/downloads.parquet`. Then add `--image-manifest artifacts/my-image-assets/manifest.json` to the platform conversion or preselected-input command.

For Docker, set `configs/local/docker/assets.json` to:

```json
{
  "roots": {"my-images": "/app/artifacts/my-images"},
  "manifests": ["/app/artifacts/my-image-assets/manifest.json"]
}
```

Restart the API after changing this configuration. Native deployments use absolute local paths in the file selected by `RECARENA_ASSET_CONFIG`.

Registered local asset IDs select self-hosted images. Items with no successful local image keep external URLs; check the download/validation reports before using this mode offline. Supported Amazon URLs have responsive CDN variants; other URLs and local assets use one supplied image. This process does not generate resized local variants.

## Completion and retries

Use a new directory for common preparation and each catalog conversion. `prepared.json` and `platform.json` identify completed stages; failures leave `failed.json` and intermediate files. Original files and fixed partitions remain unchanged. Download retries resume partial transfers; preparation/conversion retries use a new output directory.
