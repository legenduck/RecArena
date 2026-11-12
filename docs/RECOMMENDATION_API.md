# Connect a recommendation service

RecArena sends HTTP requests to a provider and stores its returned order. The provider owns retrieval, scoring, model files and preparation. It may use any language. The [bundled server](../examples/recommendation/ranker/README.md) implements this contract as an optional example.

## Address and authentication

Set `RECARENA_RANKER_URL` for one provider, or `RECARENA_RECOMMENDATION_SERVICES` to a JSON mapping of service names to addresses. For Docker, put these settings in `configs/local/docker/settings.json`. Addresses must be reachable from the API container.

Every provider request carries `Authorization: Bearer <RECARENA_INTERNAL_TOKEN>`. Configure the provider with the platform's `internal_token.secret`. This credential is separate from administrator and session-issuance credentials.

## Discovery and readiness

| Endpoint | Request | Response |
|---|---|---|
| `GET /internal/v1/policies` | No body | Array of [PolicyDefinition](../contracts/schemas/PolicyDefinition.schema.json) |
| `POST /internal/v1/policies/validate` | [PolicyValidationRequest](../contracts/schemas/PolicyValidationRequest.schema.json) | `ready: true` and the exact requested `policy` when it can serve the catalog/user/history |
| `POST /internal/v1/recommend` | [RecommendationRequest](../contracts/schemas/RecommendationRequest.schema.json) | [RecommendationResponse](../contracts/schemas/RecommendationResponse.schema.json) |

A definition contains `name`, `catalog_snapshot_id`, optional `description` and a policy binding: `family`, `policy_id`, `version`, `service_id`, `candidate_scope`, `candidate_limit`. The provider chooses `family`; the platform assigns `service_id` from its address mapping. Publish a new provider version when scoring settings or implementation change.

## Recommendation request and response

Example request with one ranking source:

```json
{
  "query": "water bottle", "catalog_snapshot_id": "catalog-v1",
  "user": {"user_id": "user-1", "history_snapshot_id": "history-v1"},
  "policy": {
    "family": "example", "service_id": "default", "policy_id": "my-policy",
    "version": "v1", "candidate_scope": "catalog-search", "candidate_limit": 200
  },
  "policy_version_id": "binding-v1", "candidates": null
}
```

Corresponding response for a one-product result:

```json
{
  "policy": {
    "family": "example", "service_id": "default", "policy_id": "my-policy",
    "version": "v1", "candidate_scope": "catalog-search", "candidate_limit": 200
  },
  "candidates": {
    "candidate_set_id": "set-001", "catalog_snapshot_id": "catalog-v1",
    "candidate_scope": "catalog-search", "query_raw": "water bottle",
    "query_normalized": "water bottle",
    "candidates": [{"product_id": "product-1", "retrieval_rank": 1}]
  },
  "ranking": {
    "candidate_set_id": "set-001", "policy_version_id": "binding-v1",
    "ranked_items": [{"product_id": "product-1", "retrieval_rank": 1, "final_rank": 1}]
  }
}
```

Use IDs from the requested catalog. Candidate IDs must be unique, with consecutive retrieval ranks starting at 1. Return every candidate exactly once, preserving its retrieval rank and assigning consecutive final ranks. Candidate count cannot exceed `candidate_limit`. Scores and diagnostics are optional and remain internal/control data.

Use a fresh `candidate_set_id` for each new set. Additional ranking sources may receive `candidates` from an earlier source; return that exact set, including its metadata. Return the exact requested policy binding and `policy_version_id`. Keep `query_raw` unchanged and normalize `query_normalized` using [the shared rule](../contracts/recarena_contracts/text.py): NFKC, removal of control characters and collapsed whitespace, with case preserved.

The platform checks these invariants and catalog availability. Private task goals and evaluation answers are not sent to the provider. The complete field definitions are in the linked JSON schemas.

## Publish a platform environment

After importing data and starting the provider, load the administrator credential and list its advertised policies:

```bash
export RECARENA_ADMIN_URL=http://127.0.0.1:5174
export RECARENA_ADMIN_TOKEN="$(cat configs/local/docker/admin_token.secret)"
curl --fail --show-error \
  -H "Authorization: Bearer $RECARENA_ADMIN_TOKEN" \
  "$RECARENA_ADMIN_URL/api/control/v1/policies"
cp configs/examples/environment.json configs/local/environment.json
```

Edit the copied [environment example](../configs/examples/environment.json):

| Field | What to enter |
|---|---|
| `bindings` | Catalog, review and history snapshot IDs returned by import |
| `presentation.ranking_sources.main.policy` | The complete `policy` object from discovery, including its assigned `service_id` |
| `presentation.ranking_sources.main.policy_version_id` | A new, unique name for this platform binding |
| `presentation.layout` | Page size, blocks and enabled shopping controls |

The example shows 10 products in five columns, with filters and cart enabled and abandonment disabled. These are explicit example settings. See [Layout](../contracts/schemas/Layout.schema.json) for other arrangements. Ranking sources in one environment must share the same candidate scope and limit.

```bash
curl --fail --show-error \
  -H "Authorization: Bearer $RECARENA_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data @configs/local/environment.json \
  "$RECARENA_ADMIN_URL/api/control/v1/environments"
```

Reload the administrator, select the draft, validate it for an imported research user, and publish it. Save a policy name pointing to the published environment. Use that name with `create_session.py --policy`. For changes, copy a published environment to a new draft; existing sessions keep their original version.

## Inputs for your own provider

`./recarena --docker sources products --catalog YOUR_CATALOG_ID --output outputs/products.json` exports [CatalogProducts](../contracts/schemas/CatalogProducts.schema.json), including variants. Choose your provider's search fields from that document. `sources history --help` describes exporting permitted interactions. Neither export includes private task definitions.
