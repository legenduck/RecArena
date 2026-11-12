"""Exact review counts before tau, optionally restricted to a recent-day window."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
from recarena_contracts.artifacts import verify_manifest
from ..timestamps import DAY_MS, milliseconds


class RecentReviews:
    def __init__(self, directory: Path):
        self.manifest = verify_manifest(directory / 'manifest.json')
        if self.manifest['artifact_type'] != 'review_timestamps' or len(self.manifest['parent_artifact_ids']) != 2:
            raise ValueError('Invalid public-review timestamp artifact')
        self.reference = json.loads((directory / 'reference.json').read_text())
        self.rows = json.loads((directory / 'product_id_to_row.json').read_text())
        self.offsets = np.load(directory / 'offsets.npy', allow_pickle=False)
        self.times = np.load(directory / 'timestamps_ms.npy', mmap_mode='r', allow_pickle=False)
        if (self.times.dtype != np.int64 or self.times.ndim != 1 or self.offsets.dtype != np.int64 or
            self.offsets.shape != (len(self.rows)+1,) or self.offsets[0] != 0 or self.offsets[-1] != len(self.times) or
            (np.diff(self.offsets) < 0).any() or set(self.rows.values()) != set(range(len(self.rows))) or
            self.manifest['counts'] != {'products':len(self.rows),'reviews':len(self.times)} or
            self.manifest['parent_artifact_ids'] != [self.reference['catalog_snapshot_id'], self.reference['review_snapshot_id']]):
            raise ValueError('Invalid review timestamp mapping')

    def counts(self, product_ids, delta_t, tau):
        if delta_t is not None and (isinstance(delta_t, bool) or not isinstance(delta_t, int) or delta_t <= 0):
            raise ValueError('delta_t must be a positive number of days or null for cumulative counts')
        tau_ms = milliseconds(tau)
        start = None if delta_t is None else tau_ms - delta_t * DAY_MS
        result = {}
        for product in product_ids:
            row = self.rows.get(product)
            if row is None:
                result[product] = 0
                continue
            values = self.times[self.offsets[row]:self.offsets[row+1]]
            lower = 0 if start is None else np.searchsorted(values, start, side='left')
            result[product] = int(np.searchsorted(values, tau_ms, side='left') - lower)
        return result

    def window(self, delta_t, tau):
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        tau_ms = milliseconds(tau)
        return {'start_inclusive': None if delta_t is None else (epoch+timedelta(milliseconds=tau_ms-delta_t*DAY_MS)).isoformat(),
                'end_exclusive': (epoch+timedelta(milliseconds=tau_ms)).isoformat()}
