"""Validated, transactional import; existing snapshot IDs cannot be overwritten."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from recarena_contracts.artifacts import canonical_hash, digest, provenance
from recarena_contracts.catalog import CatalogBundle
from recarena_contracts.manifest import ArtifactManifest
from recarena_platform.db import engine_from_env
from recarena_platform.db import catalog as db
from recarena_platform.task_validation import validate_task_utility
from recarena_platform.catalog.reviews import review_document
from recarena_platform.catalog.review_statistics import store_review_statistics


class ImmutableCatalog(ValueError):
    pass


def import_catalog_file(session, path):
    """Existing JSON bundle or its explicitly manifested streaming representation."""
    path = Path(path)
    document = json.loads(path.read_text())
    if document.get('artifact_type') == 'catalog_snapshot':
        from recarena_platform.catalog.packages import import_package
        if session.get(db.DatasetSnapshot, document['artifact_id']) is not None:
            raise ImmutableCatalog('Immutable catalog ID already registered; use a new snapshot ID')
        return import_package(session, path)
    bundle = CatalogBundle.model_validate(document)
    import_bundle(session, bundle, source_hash=digest(path), source_name=path.name)
    return bundle


def import_bundle(session: Session, bundle: CatalogBundle, *, source_hash: str, source_name: str):
    if session.get(db.DatasetSnapshot, bundle.dataset_snapshot_id):
        raise ImmutableCatalog('Immutable catalog ID already registered; use a new snapshot ID')
    source = {'name': source_name, 'sha256': source_hash}
    common = {'schema_version': '1.0', 'source_files': [source], **provenance(),
              'created_at': datetime.now(timezone.utc).isoformat(), 'files': [],
              'config_hash': canonical_hash({'schema_version': bundle.schema_version,
                                             'review_cutoff': str(bundle.review_cutoff)}),
              'warnings': ['Synthetic test fixture'] if all(p.source_provenance.get('synthetic') for p in bundle.products) else []}
    session.add(db.DatasetSnapshot(id=bundle.dataset_snapshot_id, manifest={**common,
        'artifact_id': bundle.dataset_snapshot_id, 'artifact_type': 'catalog_snapshot',
        'parent_artifact_ids': [], 'counts': {'products': len(bundle.products), 'variants': len(bundle.variants)}}))
    session.flush()
    session.add_all([db.Product(dataset_snapshot_id=p.dataset_snapshot_id, product_id=p.product_id,
                               document=p.model_dump(mode='json')) for p in bundle.products])
    session.flush()
    for v in bundle.variants:
        session.add(db.Variant(dataset_snapshot_id=v.dataset_snapshot_id, variant_id=v.variant_id,
            product_id=v.product_id, unit_price_minor=v.unit_price_minor, currency=v.currency,
            is_available=v.is_available, is_purchasable=v.is_purchasable, document=v.model_dump(mode='json')))
    session.add(db.ReviewSnapshot(id=bundle.review_snapshot_id, dataset_snapshot_id=bundle.dataset_snapshot_id,
        cutoff=bundle.review_cutoff, manifest={**common, 'artifact_id': bundle.review_snapshot_id,
            'artifact_type': 'review_snapshot', 'parent_artifact_ids': [bundle.dataset_snapshot_id],
            'counts': {'reviews': len(bundle.reviews)}}))
    session.add(db.HistorySnapshot(id=bundle.history_snapshot_id, dataset_snapshot_id=bundle.dataset_snapshot_id,
        manifest={**common, 'artifact_id': bundle.history_snapshot_id, 'artifact_type': 'history_snapshot',
            'parent_artifact_ids': [bundle.dataset_snapshot_id], 'counts': {'interactions': len(bundle.history)}}))
    session.flush()
    session.add_all([db.HistoricalUser(history_snapshot_id=bundle.history_snapshot_id, user_id=u)
                     for u in sorted({r.user_id for r in bundle.history})])
    session.flush()
    rating_counts = defaultdict(Counter)
    for r in bundle.reviews:
        rating_counts[r.product_id][r.rating] += 1
        session.add(db.Review(review_snapshot_id=r.review_snapshot_id, review_id=r.review_id,
            dataset_snapshot_id=bundle.dataset_snapshot_id, product_id=r.product_id,
            timestamp_utc=r.timestamp_utc, document=review_document(r)))
    store_review_statistics(session, bundle.dataset_snapshot_id, bundle.review_snapshot_id,
        (p.product_id for p in bundle.products), rating_counts)
    for r in bundle.history:
        session.add(db.HistoricalInteraction(history_snapshot_id=r.history_snapshot_id, user_id=r.user_id,
            product_id=r.product_id, dataset_snapshot_id=bundle.dataset_snapshot_id,
            timestamp_utc=r.timestamp_utc, document=r.model_dump(mode='json')))
    for t in bundle.tasks:
        validate_task_utility(session,t)
        session.add(db.TaskVersion(id=f'{t.task_id}:v{t.version}', task_id=t.task_id, version=t.version,
            dataset_snapshot_id=t.catalog_snapshot_id, document=t.model_dump(mode='json')))
    session.flush()
    for cls, identifier in [(db.DatasetSnapshot, bundle.dataset_snapshot_id),
                            (db.ReviewSnapshot, bundle.review_snapshot_id),
                            (db.HistorySnapshot, bundle.history_snapshot_id)]:
        ArtifactManifest.model_validate(session.get(cls, identifier).manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True, type=Path)
    args = parser.parse_args()
    engine = engine_from_env()
    with Session(engine) as session, session.begin():
        bundle = import_catalog_file(session, args.bundle)
    engine.dispose()
    print(f'Registered immutable catalog {bundle.dataset_snapshot_id}')


if __name__ == '__main__':
    main()
