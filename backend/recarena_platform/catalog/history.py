from sqlalchemy import select
from recarena_contracts.history import history_fingerprint_sorted
from recarena_platform.db import catalog as db


def fixed_history_fingerprint(session, history_id):
    table = db.HistoricalInteraction
    rows = session.execute(select(table.user_id, table.product_id, table.timestamp_utc).where(
        table.history_snapshot_id == history_id).order_by(table.user_id.collate('C'),
        table.product_id.collate('C'), table.timestamp_utc).execution_options(yield_per=10000))
    return history_fingerprint_sorted((user, product, timestamp.timestamp()) for user, product, timestamp in rows)
