"""Consistent exports of recorded shopping facts and their execution context."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from uuid import uuid4
import zipfile
import shutil
from threading import Event, Thread

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recarena_contracts.artifacts import digest,provenance,write_json
from recarena_contracts.layout import from_environment
from recarena_platform.reporting.export_io import write_csv, write_json_array, verify_export
from recarena_platform.reporting.snapshots import open_snapshot, RUN_FIELDS, PURCHASE_FIELDS
from recarena_platform.db import runtime as db
from recarena_platform.reporting.comparisons import audit
from recarena_platform.outcomes import Outcome, rejected

def export_lock_key(identifier):
    return int(identifier.replace('-','')[:16],16) & ((1<<63)-1)


@contextmanager
def export_lock(engine,identifier):
    # Session lock survives commits while the synchronous export writes files.
    # Process/connection death releases it; a worker can then identify an orphan.
    with engine.connect() as connection:
        acquired=connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':export_lock_key(identifier)})
        connection.commit()
        try: yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':export_lock_key(identifier)})
                    connection.commit()
                except Exception:
                    connection.invalidate()


def recover_interrupted_exports(engine):
    with Session(engine) as session:
        pending=list(session.scalars(select(db.ExportRecord.id).where(db.ExportRecord.state=='PENDING')))
    recovered=0
    for identifier in pending:
        with export_lock(engine,identifier) as acquired:
            if not acquired: continue
            with Session(engine) as session,session.begin():
                record=session.scalar(select(db.ExportRecord).where(db.ExportRecord.id==identifier).with_for_update())
                if record.state!='PENDING': continue
                record.state,record.error_code='FAILED','INTERRUPTED_EXPORT'
                # Retain partial output exactly; a retry creates a new export ID.
                recovered+=1
    return recovered


class ExportService:
    def __init__(self,engine):
        self.engine=engine

    def create(self,experiment_id=None,run_ids=None,filters=None):
        identifier=str(uuid4())
        with export_lock(self.engine,identifier) as acquired:
            if not acquired: return rejected('EXPORT_BUSY',409)
            return self._create_locked(experiment_id,identifier,run_ids,filters)

    def _create_locked(self,experiment_id,identifier,run_ids=None,filters=None):
        directory=Path(os.environ.get('RECARENA_EXPORT_ROOT','outputs/exports')).resolve()/identifier
        with Session(self.engine) as session,session.begin():
            if experiment_id and session.get(db.Experiment,experiment_id) is None:
                return rejected('RESULT_NOT_FOUND',404)
            session.add(db.ExportRecord(id=identifier,experiment_id=experiment_id,state='PENDING',directory=str(directory),
                scope={'run_ids':list(run_ids) if run_ids is not None else None,'filters':filters}))
        try:
            directory.mkdir(parents=True,exist_ok=False)
            with open_snapshot(self.engine,experiment_id,run_ids,filters) as data:
                scope=data['scope']
                artifacts = data['artifacts']
                needed=set()
                for environment in data['environments']:
                    needed.update(environment[key] for key in ('dataset_snapshot_id','review_snapshot_id','history_snapshot_id'))
                    from recarena_contracts.legacy_policy import recorded_artifacts
                    needed.update(recorded_artifacts(environment['config']))
                # Export historical observations without contacting a model server.
                # Old runs may predate metadata caching; report missing metadata explicitly.
                for artifact in needed:
                    artifacts.setdefault(artifact, {'artifact_id': artifact, 'metadata_status': 'unavailable'})
                (directory/'attachments').mkdir()
                write_json(directory/'experiment.json',data['experiment'])
                write_json(directory/'scope.json',data['scope'])
                write_json(directory/'environment_snapshot.json',data['environments'])
                write_json(directory/'policy_bindings.json', [{
                    'environment_id': value['id'],
                    'ranking_sources': from_environment(value['config']).model_dump(mode='json')['ranking_sources']
                } for value in data['environments']])
                write_json(directory/'tasks.json',data['tasks'])
                write_csv(directory/'runs.csv',data['runs'],RUN_FIELDS)
                write_csv(directory/'purchases.csv',data['purchases'],PURCHASE_FIELDS)
                for filename,records in [('events.jsonl',data['events']),('ranking_results.jsonl',data['rankings']),
                                         ('placements.jsonl',data['placements'])]:
                    with (directory/filename).open('x') as stream:
                        for record in records:
                            stream.write(json.dumps(record,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n')
                write_json(directory/'telemetry.json',data['telemetry'])
                write_json_array(directory/'telemetry_submissions.json',data['telemetry_submissions'])
                def attachments():
                    for attachment in data['attachments']:
                        source=Path(attachment['storage_path'])
                        if digest(source)!=attachment['sha256'] or source.stat().st_size!=attachment['size_bytes']:
                            raise ValueError('Attachment integrity mismatch')
                        target=directory/'attachments'/attachment['run_id']/attachment['attachment_id']
                        target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(source,target)
                        yield {k:v for k,v in attachment.items() if k!='storage_path'} | {'path':str(target.relative_to(directory))}
                write_json_array(directory/'attachments.json',attachments())
                write_json(directory/'artifact_manifest.json',[artifacts[key] for key in sorted(needed)])
            write_json(directory/'export_manifest.json',{'schema_version':'2.0','export_id':identifier,'experiment_id':experiment_id,
                **provenance(),'files':[{'path':str(p.relative_to(directory)),'size_bytes':p.stat().st_size,'sha256':digest(p)}
                    for p in sorted(directory.rglob('*')) if p.is_file()]})
            verify_export(directory)
            archive=directory.with_suffix('.zip')
            with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as stream:
                for path in sorted(directory.rglob('*')):
                    stream.write(path,path.relative_to(directory))
            with Session(self.engine) as session,session.begin():
                record=session.get(db.ExportRecord,identifier)
                if record.state!='PENDING': raise ValueError('Export attempt interrupted')
                record.state,record.directory,record.archive_path='COMPLETED',str(directory),str(archive)
                audit(session,'experiment_exported' if experiment_id else 'rollouts_exported',experiment_id or identifier,{'export_id':identifier,'scope':scope})
            return Outcome({'export_id':identifier,'state':'COMPLETED'})
        except Exception as error:
            with Session(self.engine) as session,session.begin():
                record=session.get(db.ExportRecord,identifier)
                if record.state=='PENDING': record.state,record.error_code='FAILED',type(error).__name__
                record.directory=str(directory) if directory.exists() else None
            return rejected('EXPORT_FAILED',422)


class ExportRecoveryWorker:
    """Mark abandoned exports as failed without evaluating shopping outcomes."""
    def __init__(self,engine):
        self.engine=engine
        self.stopped=Event()
        self.last_error_type=None
        self.thread=Thread(target=self.loop,name='recarena-export-recovery',daemon=True)

    def loop(self):
        while not self.stopped.is_set():
            try:
                recover_interrupted_exports(self.engine)
                self.last_error_type=None
            except Exception as error:
                self.last_error_type=type(error).__name__
            self.stopped.wait(1)

    def start(self): self.thread.start()
    def stop(self): self.stopped.set();self.thread.join(timeout=10)
