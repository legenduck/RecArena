"""Preserve immutable policy ID meanings, including existing published versions."""
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    table=op.create_table('policy_versions',sa.Column('id',sa.String(),primary_key=True),
        sa.Column('config',postgresql.JSONB(),nullable=False),sa.Column('config_hash',sa.String(64),nullable=False))
    connection=op.get_bind()
    values={}
    for (config,) in connection.execute(sa.text("SELECT config FROM environment_versions WHERE state='PUBLISHED'")):
        sources=config.get('ranking_sources',{})
        if not sources and 'policy' in config:
            sources={'main':{'policy':config['policy'],'policy_version_id':config['policy_version_id']}}
        for source in sources.values():
            identifier,policy=source['policy_version_id'],source['policy']
            if identifier in values and values[identifier]!=policy:
                raise ValueError(f'Published policy version conflict: {identifier}')
            values[identifier]=policy
    for identifier,config in values.items():
        checksum=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        connection.execute(table.insert().values(id=identifier,config=config,config_hash=checksum))
    op.execute('CREATE TRIGGER policy_versions_immutable BEFORE UPDATE ON policy_versions FOR EACH ROW EXECUTE FUNCTION recagent_fixed_record_update()')


def downgrade():
    op.execute('DROP TRIGGER policy_versions_immutable ON policy_versions')
    op.drop_table('policy_versions')
