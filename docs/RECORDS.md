# Read shopping records

Use **Rollouts & results** in the administrator to inspect runs, purchases and event timelines, or download an export. Each export captures the selected runs at one database snapshot. Its files are under `outputs/exports/<export_id>/`, with a ZIP alongside that directory.

## Export files

| File | Contents |
|---|---|
| `runs.csv` | Run ID, research user, environment/policy references, labels, state and end reason |
| `events.jsonl` | One recorded event per line, with source, timestamps, identifiers and payload |
| `ranking_results.jsonl` | Original queries, candidates, provider rankings/scores and presentation settings |
| `placements.jsonl` | Issued product positions linked to their run and result snapshot |
| `purchases.csv` | Confirmed purchase items, options, quantities, prices and currency totals |
| `environment_snapshot.json`, `policy_bindings.json` | Applied environment definitions and recommendation bindings |
| `scope.json` | Selected runs, filters and `data_as_of` timestamp |
| `artifact_manifest.json` | Available metadata for referenced data/preparation artifacts |
| `export_manifest.json` | Export format version, build identity when provided, file sizes and SHA-256 hashes |

`experiment.json` describes a saved comparison when one was selected. `tasks.json` contains referenced task definitions. Compatibility files (`telemetry.json`, `telemetry_submissions.json`, `attachments.json` and `attachments/`) preserve archived external records when present. Their presence does not mean that the platform collects agent-internal traces. Exports contain no platform evaluation results or metric summary.

## What the events mean

| Event or family | Recorded fact |
|---|---|
| `rollout_initialized`, `session_accessed`, termination events | Session setup, access, and recorded end state/reason |
| `search_submitted` | Submitted query |
| `candidate_set_used`, `ranking_computed` | Provider candidates and ranking were stored |
| `items_served` | Server returned a particular list, page and filter state |
| `item_list_rendered` | Browser reported rendering that list |
| `product_clicked` | Browser reported selecting a position in a list |
| `product_detail_served`, `reviews_served`, `cart_served` | Server returned detail, reviews or cart content |
| `page_viewed`, `reviews_rendered`, `review_section_entered`, `scroll_sampled` | Browser reports of page/review display, review-region entry or sampled scroll position |
| `selection_updated`, `cart_item_added`, `cart_item_updated`, `cart_item_removed` | Server accepted an option, quantity or cart change |
| `purchase_requested`, `purchase_rejected`, `purchase_confirmed` | Purchase attempt, refusal, or committed purchase |

`measurement_basis=served` marks returned content; `observed` marks browser rendering reports. A rendered list does not establish that every card entered the viewport or that an agent read it. Purchase requests and cart contents are not confirmed purchases. Other events may have no measurement basis.

Filters select from the stored candidates without another provider request. `items_served` retains the applied filters and displayed order. The candidate set and provider ranks remain available separately. Page/filter responses alone cannot reliably distinguish a deliberate action from a reload. The platform does not record every UI action or the agent's reasoning, tool calls, screenshots or token usage.

## Connect the records

- The session API's `rollout_id` matches `runs.csv.id` and other records' `run_id`. The URL's opaque `session_id` is distinct from the internal `shop_session_id`.
- `result_snapshot_id` connects events and placements to one `ranking_results.jsonl` record. That record contains `candidate_set` and `rankings`, keyed by source name.
- In event schema `2.0`, `candidate_set_used` and `ranking_computed` contain references instead of full provider bodies. For a ranking event, use `rankings[event.payload.source_id]` in the referenced snapshot. Schema `1.0` events retain their original payloads.
- `placement_id` connects a displayed/selected position to `placements.jsonl`, which carries `product_id`, snapshot and source-position information. `list_presentation_id` distinguishes separate browser renderings of a list.
- For current browser reports, `page_instance_id` identifies the browser document and `view_id` identifies the server-issued view. Client navigation can have several views in one document; a reload creates a new document ID.
- Older browser events may use a view ID as `page_instance_id`. Newly received old-format reports have `page_instance_kind=legacy_view`; older stored records may have no kind or `view_id`. Do not treat those IDs as document identities.

The [EventEnvelope schema](../contracts/schemas/EventEnvelope.schema.json) lists the common fields. `schema_version` describes an event's shape. `recording_method` is `rendered_list` for the current list-rendering convention; it is separate from `measurement_basis`, which distinguishes served and observed records. A missing method means it was not recorded. The export manifest has a separate version for the file bundle.

## Time, delivery and repeated actions

`occurred_at` is the source timestamp; browser timestamps use the browser clock. `received_at` is the server recording time. `sequence` orders stored events within a run. Current clients use `client_sequence` within a browser document; older clients restarted it per view. Receipt order is not a cross-source causal order.

Retransmissions reuse their event ID and do not add another event. A repeated action with a new ID is a separate record. `late_received` marks records received after their run ended or their session context ceased to be current; they stay attached to the original context. Occurrence relative to termination can remain unknown.

Browser reports are buffered and retried. Available browser storage retains unacknowledged events across reloads; blocked/cleared storage or interruption before persistence can still lose reports. An export includes only records present in its database snapshot. Export again to include later arrivals. An empty browser-event list alone does not prove that the site was unused.

## Purchases and integrity

Purchase `items`, selected options and currency totals are JSON cells in CSV. Prices are in minor currency units. Missing amounts remain null; totals in different currencies must be interpreted separately. Use confirmed items and quantities for purchase analysis, including multi-item carts.

To verify an export's file inventory, sizes and hashes:

```bash
./recarena --docker verify-export \
  --export-directory outputs/exports/EXPORT_ID
```

This checks file integrity. Definitions such as Agent Steps, conversion, PS/QC/Hit or exposure quality belong to the study's analysis. The [judging example](../examples/judging/README.md) consumes prepared tasks and selected product IDs separately from these platform records.
