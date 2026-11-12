"""Researcher CLI over existing immutable import/registration contracts.

These commands consume explicitly named prepared inputs. They do not locate,
download, normalize, or select an Amazon dataset.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import write_json
from recarena_contracts.catalog import CatalogBundle


def add_commands(commands):
    data = commands.add_parser('data', help='Register an explicitly supplied prepared catalog bundle')
    operation = data.add_subparsers(dest='operation', required=True)
    importing = operation.add_parser('import')
    importing.add_argument('--bundle', type=Path, required=True, help='Prepared JSON bundle or catalog-jsonl-v1 manifest.json')

    sources = commands.add_parser('sources', help='Export registered products or permitted history')
    operation = sources.add_subparsers(dest='operation', required=True)
    corpus = operation.add_parser('products')
    corpus.add_argument('--catalog', required=True)
    corpus.add_argument('--output', type=Path, required=True)
    history = operation.add_parser('history')
    history.add_argument('--history', required=True)
    history.add_argument('--output', type=Path, required=True)


def execute(args):
    from recarena_platform.db import engine_from_env
    from recarena_platform.db import catalog as catalog
    from recarena_platform.db import runtime as db
    engine = engine_from_env()
    try:
        if args.command == 'data':
            from recarena_platform.catalog.artifacts import prepared_path
            from recarena_platform.catalog.importing import import_catalog_file
            path = prepared_path(args.bundle)
            from recarena_contracts.artifacts import digest
            source_hash = digest(path)
            with Session(engine) as session, session.begin():
                bundle = import_catalog_file(session, path)
                session.add(db.OperatorAuditEvent(action='catalog_registered',
                    target_id=bundle.dataset_snapshot_id, document={'source_hash': source_hash}))
            return {'catalog_snapshot_id': bundle.dataset_snapshot_id,
                    'review_snapshot_id': bundle.review_snapshot_id,
                    'history_snapshot_id': bundle.history_snapshot_id}
        with Session(engine) as session:
            if args.operation == 'products':
                from recarena_platform.catalog.export import export_products
                document = export_products(session, args.catalog).model_dump(mode='json')
                count = len(document['products'])
            else:
                if session.get(catalog.HistorySnapshot, args.history) is None:
                    raise ValueError('Unknown registered history snapshot')
                rows = session.scalars(select(catalog.HistoricalInteraction).where(
                    catalog.HistoricalInteraction.history_snapshot_id == args.history).order_by(
                    catalog.HistoricalInteraction.user_id, catalog.HistoricalInteraction.product_id))
                interactions = [{'user_id': row.user_id, 'product_id': row.product_id,
                                 'timestamp': row.timestamp_utc.timestamp()} for row in rows]
                document = {'history_snapshot_id': args.history, 'interactions': interactions}
                count = len(interactions)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, document)
        return {'output': str(args.output.resolve()), 'count': count}
    finally:
        engine.dispose()
