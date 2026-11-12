import hashlib
import json


def history_fingerprint(records):
    """Fingerprint the actual positive training signal and its observation times."""
    rows = sorted((str(r['user_id']), str(r['product_id']), float(r['timestamp'])) for r in records)
    return history_fingerprint_sorted(rows)


def history_fingerprint_sorted(rows):
    """Same canonical digest as the original function, without one huge JSON string.

Rows must already be sorted (user ID, parent product ID, timestamp) tuples.
This also supports a database/file iterator for a large immutable history.
"""
    result = hashlib.sha256(b'[')
    previous = None
    for row in rows:
        row = (str(row[0]), str(row[1]), float(row[2]))
        if previous is not None:
            if row < previous:
                raise ValueError('History fingerprint input is not sorted')
            result.update(b',')
        result.update(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False).encode())
        previous = row
    result.update(b']')
    return result.hexdigest()
