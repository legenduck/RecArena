"""Catalog records and HTTP resource metadata; no recommendation file access."""
import os
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_platform.db import catalog as catalog
from recarena_platform.db import runtime as db


def prepared_path(filename):
    """Restrict local catalog imports, never recommendation server files."""
    path = Path(filename).resolve()
    root = Path(os.environ.get('RECARENA_ARTIFACT_ROOT', 'artifacts')).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path outside prepared catalog root')
    return path


def saved_resources(session):
    values = {row.id: row.manifest for row in session.scalars(select(db.RegisteredArtifact))}
    for model in (catalog.DatasetSnapshot, catalog.ReviewSnapshot, catalog.HistorySnapshot):
        values.update({row.id: row.manifest for row in session.scalars(select(model))})
    return values


class ArtifactService:
    def __init__(self, engine, ranking):
        self.engine, self.ranking = engine, ranking

    def list(self):
        with Session(self.engine) as session:
            catalog_types = {'catalog_snapshot', 'review_snapshot', 'history_snapshot'}
            return {'artifacts': [
                {'manifest': value, 'registered': True, 'ready': True}
                for value in saved_resources(session).values() if value.get('artifact_type') in catalog_types]}
