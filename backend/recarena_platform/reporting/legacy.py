"""Read-only compatibility for previously stored external records.

There is no ingestion API. Return the latest submitted document unchanged;
the full submission history is retained separately in each export.
"""


def telemetry_summary(records):
    latest = {}
    for record in sorted(records, key=lambda r: r.sequence):
        latest[record.run_id] = record.document
    return latest
