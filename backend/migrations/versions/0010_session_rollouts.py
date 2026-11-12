"""Independent sessions, immutable request contexts and self-contained entry settings.

Historical JSON documents, run states, IDs and evaluation results are unchanged.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    orphan = connection.execute(sa.text('''SELECT count(*) FROM shop_sessions s LEFT JOIN runs r ON r.id=s.run_id
        WHERE r.id IS NULL OR r.user_id IS NULL OR r.history_snapshot_id IS NULL''')).scalar_one()
    if orphan:
        raise RuntimeError('Session user backfill is ambiguous; migration aborted without inventing users')
    for name in ('user_id', 'history_snapshot_id', 'current_context_id'):
        op.add_column('shop_sessions', sa.Column(name, sa.String(), nullable=True))
    op.add_column('shop_sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_foreign_key('session_history_user_fk', 'shop_sessions', 'historical_users',
                          ['history_snapshot_id', 'user_id'], ['history_snapshot_id', 'user_id'])
    op.create_table('shop_contexts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('shop_session_id', sa.String(), sa.ForeignKey('shop_sessions.id'), nullable=False),
        sa.Column('run_id', sa.String(), sa.ForeignKey('runs.id'), unique=True),
        sa.Column('user_id', sa.String()), sa.Column('history_snapshot_id', sa.String()),
        sa.Column('environment_version_id', sa.String(), sa.ForeignKey('environment_versions.id')),
        sa.Column('next_sequence', sa.BigInteger(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('id', 'run_id'),
        sa.ForeignKeyConstraint(['history_snapshot_id', 'user_id'], ['historical_users.history_snapshot_id', 'historical_users.user_id']))
    op.create_index('ix_shop_contexts_shop_session_id', 'shop_contexts', ['shop_session_id'])
    op.execute('''INSERT INTO shop_contexts (id,shop_session_id,run_id,user_id,history_snapshot_id,environment_version_id,created_at)
        SELECT r.id,s.id,r.id,r.user_id,r.history_snapshot_id,r.environment_version_id,s.created_at
        FROM shop_sessions s JOIN runs r ON r.id=s.run_id''')
    op.execute('''UPDATE shop_sessions s SET user_id=r.user_id,history_snapshot_id=r.history_snapshot_id,
        current_context_id=r.id,last_seen_at=s.created_at FROM runs r WHERE r.id=s.run_id''')
    op.create_foreign_key('session_current_context_fk', 'shop_sessions', 'shop_contexts', ['current_context_id'], ['id'])
    op.add_column('runs', sa.Column('shop_session_id', sa.String(), sa.ForeignKey('shop_sessions.id', name='run_shop_session_fk')))
    op.execute('UPDATE runs r SET shop_session_id=s.id FROM shop_sessions s WHERE s.run_id=r.id')
    for name in ('requested_policy', 'agent_label', 'external_task_id', 'client_run_id', 'entry_encoding', 'end_reason'):
        op.add_column('runs', sa.Column(name, sa.String(), nullable=True))
    for name in ('requested_policy', 'agent_label', 'external_task_id', 'client_run_id'):
        op.create_index('ix_runs_' + name, 'runs', [name])
    for name in ('entry_config', 'entry_snapshot'):
        op.add_column('runs', sa.Column(name, postgresql.JSONB(), nullable=True))
    op.add_column('runs', sa.Column('configuration_digest', sa.String(64), nullable=True))
    op.add_column('runs', sa.Column('first_interaction_at', sa.DateTime(timezone=True), nullable=True))

    owned = ('result_snapshots', 'placements', 'product_view_states', 'purchases', 'qualified_impressions', 'client_event_receipts')
    for table in (*owned, 'events'):
        op.add_column(table, sa.Column('context_id', sa.String(), sa.ForeignKey('shop_contexts.id')))
        op.execute(f'UPDATE {table} t SET context_id=c.id FROM shop_contexts c WHERE c.run_id=t.run_id')
        if table in owned:
            op.alter_column(table, 'context_id', nullable=False)
    for table, key in (('product_view_states', 'product_id'), ('qualified_impressions', 'key_hash'), ('client_event_receipts', 'event_id')):
        op.drop_constraint(sa.inspect(connection).get_pk_constraint(table)['name'], table, type_='primary')
        op.create_primary_key(table + '_pkey', table, ['context_id', key])
    for table in (*owned, 'events'):
        op.alter_column(table, 'run_id', nullable=True)
    for unique in sa.inspect(connection).get_unique_constraints('result_snapshots'):
        if unique['column_names'] == ['run_id', 'client_request_id']:
            op.drop_constraint(unique['name'], 'result_snapshots', type_='unique')
    op.create_unique_constraint('result_context_request_unique', 'result_snapshots', ['context_id', 'client_request_id'])
    op.create_unique_constraint('result_id_context_unique', 'result_snapshots', ['id', 'context_id'])
    op.create_unique_constraint('placement_id_context_unique', 'placements', ['id', 'context_id'])
    op.create_foreign_key('placement_result_context_fk', 'placements', 'result_snapshots', ['result_snapshot_id', 'context_id'], ['id', 'context_id'])
    op.create_foreign_key('purchase_placement_context_fk', 'purchases', 'placements', ['origin_placement_id', 'context_id'], ['id', 'context_id'])
    op.create_unique_constraint('purchase_context_request_unique', 'purchases', ['context_id', 'idempotency_key'])
    for table in ('purchases', 'events'):
        op.add_column(table, sa.Column('shop_session_id', sa.String(), sa.ForeignKey('shop_sessions.id')))
        op.execute(f'UPDATE {table} t SET shop_session_id=c.shop_session_id FROM shop_contexts c WHERE c.id=t.context_id')
    op.alter_column('purchases', 'shop_session_id', nullable=False)
    op.add_column('purchases', sa.Column('user_id', sa.String()))
    op.execute('UPDATE purchases p SET user_id=r.user_id FROM runs r WHERE r.id=p.run_id')
    op.alter_column('purchases', 'user_id', nullable=False)
    op.create_unique_constraint('event_context_identity_unique', 'events', ['context_id', 'source', 'event_id'])
    op.create_unique_constraint('event_context_sequence_unique', 'events', ['context_id', 'sequence'])
    op.create_table('site_settings', sa.Column('id', sa.String(), primary_key=True), sa.Column('config', postgresql.JSONB(), nullable=False))
    op.create_table('bootstrap_receipts',
        sa.Column('shop_session_id', sa.String(), sa.ForeignKey('shop_sessions.id'), primary_key=True),
        sa.Column('request_key', sa.String(160), primary_key=True),
        sa.Column('configuration_digest', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(), sa.ForeignKey('runs.id'), nullable=False))
    op.alter_column('exports', 'experiment_id', nullable=True)
    op.add_column('exports', sa.Column('scope', postgresql.JSONB(), nullable=True))
    op.drop_column('shop_sessions', 'run_id')
    op.drop_table('claim_tokens')
    # Context identity/conditions never change, including after a rollout ends.
    op.execute('''CREATE FUNCTION recarena_context_identity() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (to_jsonb(NEW)-'next_sequence') IS DISTINCT FROM (to_jsonb(OLD)-'next_sequence') THEN
          RAISE EXCEPTION 'Shopping context identity is immutable';
        END IF;
        RETURN NEW;
      END $$''')
    op.execute('CREATE TRIGGER shop_context_identity BEFORE UPDATE ON shop_contexts FOR EACH ROW EXECUTE FUNCTION recarena_context_identity()')


def downgrade():
    raise RuntimeError('Cannot collapse ordinary sessions and repeat purchases into the legacy one-run schema without data loss. Restore a verified backup explicitly.')
