"""One filter contract shared by the administrator list and exports."""
from sqlalchemy import select, or_, cast, literal, func
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from recarena_platform.db import runtime as db

FIELDS = ('run_id','user_id','requested_policy','applied_policy','agent_label','external_task_id','client_run_id','state','run_kind','recording_method')


def filtered_runs(filters=None):
    filters = {k:v for k,v in (filters or {}).items() if v is not None and v != ''}
    if set(filters)-set(FIELDS): raise ValueError('Unknown rollout filter')
    query = select(db.Run)
    for key,value in filters.items():
        if key=='applied_policy':
            query=query.join(db.EnvironmentVersion,db.EnvironmentVersion.id==db.Run.environment_version_id).where(or_(
                db.EnvironmentVersion.config['policy']['family'].astext==value,
                func.jsonb_path_exists(db.EnvironmentVersion.config,
                    cast(literal('$.ranking_sources.*.policy.family ? (@ == $family)'),JSONPATH),
                    cast({'family':value},JSONB))))
        elif key=='recording_method' and value=='not_recorded':
            query=query.where(db.Run.recording_method.is_(None))
        else:
            query=query.where(getattr(db.Run,'id' if key=='run_id' else key)==value)
    return query
