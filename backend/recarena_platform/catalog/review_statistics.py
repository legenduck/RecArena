"""Persist counts accumulated while importing an immutable public review snapshot."""
from itertools import islice

from sqlalchemy import insert

from recarena_platform.db.catalog import ReviewStatistics


def rating_distribution(counts):
    # Keep valid fractional ratings; never infer missing reviews.
    return [{'rating': rating, 'count': count} for rating, count in sorted(counts.items(), reverse=True)]


def store_review_statistics(session, dataset_id, snapshot_id, product_ids, counts):
    """Use the caller's import transaction; failures roll back catalog and counts."""
    rows = ({'review_snapshot_id': snapshot_id, 'dataset_snapshot_id': dataset_id,
             'product_id': product_id, 'rating_counts': rating_distribution(counts.get(product_id, {}))}
            for product_id in product_ids)
    while batch := list(islice(rows, 1000)):
        session.execute(insert(ReviewStatistics), batch)
