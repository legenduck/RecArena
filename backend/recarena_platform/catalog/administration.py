"""Append-only administrative history registration."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import canonical_hash, provenance
from recarena_platform.db import catalog as db
from recarena_platform.reporting.comparisons import audit
from recarena_platform.outcomes import Outcome, rejected


class AdminDataService:
    def __init__(self, engine):
        self.engine = engine

    def import_history(self, body):
        with Session(self.engine) as session, session.begin():
            if session.get(db.HistorySnapshot,body.history_snapshot_id):
                return rejected('ARTIFACT_IMMUTABLE',409)
            if session.get(db.DatasetSnapshot,body.catalog_snapshot_id) is None:
                return rejected('ARTIFACT_MISMATCH',422)
            products = set(session.scalars(select(db.Product.product_id).where(db.Product.dataset_snapshot_id == body.catalog_snapshot_id)))
            if any(row.product_id not in products for row in body.interactions):
                return rejected('ARTIFACT_MISMATCH',422)
            source_hash = canonical_hash(body.model_dump(mode='json'))
            manifest = {'schema_version':'1.0','artifact_id':body.history_snapshot_id,'artifact_type':'history_snapshot',
                'created_at':datetime.now(timezone.utc).isoformat(), **provenance(),
                'source_files':[{'name':'canonical-admin-history-request.json','sha256':source_hash}],
                'config_hash':canonical_hash(body.provenance),'parent_artifact_ids':[body.catalog_snapshot_id],
                'counts':{'users':len(body.user_ids),'interactions':len(body.interactions)},'files':[],'warnings':[]}
            session.add(db.HistorySnapshot(id=body.history_snapshot_id,dataset_snapshot_id=body.catalog_snapshot_id,manifest=manifest))
            session.flush()
            session.add_all([db.HistoricalUser(history_snapshot_id=body.history_snapshot_id,user_id=user) for user in body.user_ids])
            session.flush()
            for row in body.interactions:
                session.add(db.HistoricalInteraction(history_snapshot_id=body.history_snapshot_id,user_id=row.user_id,
                    product_id=row.product_id,dataset_snapshot_id=body.catalog_snapshot_id,timestamp_utc=row.timestamp_utc,
                    document=row.model_dump(mode='json')))
            audit(session,'history_registered',body.history_snapshot_id,{'source_hash':source_hash,'source_provenance':body.provenance})
            return Outcome({'history_snapshot_id':body.history_snapshot_id,'manifest':manifest})
