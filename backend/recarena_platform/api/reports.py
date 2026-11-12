"""HTTP reports boundary."""
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from recarena_platform.db import runtime as db
from recarena_contracts.admin import ExportCreate
from recarena_platform.reporting.exports import ExportService
from recarena_platform.reporting.legacy import telemetry_summary
from recarena_platform.shopping.purchases import purchase_dto
from recarena_platform.api.dependencies import admin, outcome
from fastapi import APIRouter
router = APIRouter()


@router.post('/api/control/v1/exports', dependencies=[Depends(admin)])
def create_export(body: ExportCreate,request: Request):
    return outcome(request,ExportService(request.app.state.engine).create(body.experiment_id,body.run_ids,body.filters))


@router.get('/api/control/v1/exports/{export_id}', dependencies=[Depends(admin)])
def export_status(export_id: str,request: Request):
    with Session(request.app.state.engine) as session:
        record=session.get(db.ExportRecord,export_id)
        if record is None:
            raise HTTPException(404,'RESULT_NOT_FOUND')
        return {'request_id':request.state.request_id,'export_id':record.id,'experiment_id':record.experiment_id,
            'state':record.state,'error_code':record.error_code,
            'download_path':f'/api/control/v1/exports/{record.id}/download' if record.state=='COMPLETED' else None}


@router.get('/api/control/v1/exports/{export_id}/download', dependencies=[Depends(admin)])
def download_export(export_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        record=session.get(db.ExportRecord,export_id)
        if record is None or record.state!='COMPLETED':
            raise HTTPException(404,'RESULT_NOT_FOUND')
        return FileResponse(record.archive_path,media_type='application/zip',filename=f'recarena-{record.id}.zip')


@router.get('/api/control/v1/runs/{run_id}/results', dependencies=[Depends(admin)])
def inspect_results(run_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        if session.get(db.Run, run_id) is None:
            raise HTTPException(404, 'RESULT_NOT_FOUND')
        purchase = session.scalar(select(db.Purchase).where(db.Purchase.run_id == run_id))
        rankings = list(session.scalars(select(db.ResultSnapshot).where(db.ResultSnapshot.run_id == run_id)))
        placements=list(session.scalars(select(db.Placement).where(db.Placement.run_id==run_id)))
        telemetry=list(session.scalars(select(db.RunnerTelemetryRecord).where(db.RunnerTelemetryRecord.run_id==run_id).order_by(db.RunnerTelemetryRecord.sequence)))
        attachments=list(session.scalars(select(db.RunAttachment).where(db.RunAttachment.run_id==run_id).order_by(db.RunAttachment.attachment_id)))
        profile=session.get(db.BrowserProfile,run_id)
        return {'request_id': request.state.request_id, 'purchase': purchase_dto(purchase) if purchase else None,
                'ranking_results': [{'result_snapshot_id': r.id, **r.document} for r in rankings],
                'placements':[{'placement_id':p.id,'result_snapshot_id':p.result_snapshot_id,'product_id':p.product_id,**p.document} for p in placements],
                'runner_telemetry':telemetry_summary(telemetry).get(run_id),
                'telemetry_submission_count':len(telemetry),
                'browser_profile':({'state':profile.state,**profile.document} if profile else None),
                'attachments':[a.document for a in attachments]}


@router.get('/api/control/v1/runs/{run_id}/attachments/{attachment_id}',dependencies=[Depends(admin)])
def download_attachment(run_id: str,attachment_id: str,request: Request):
    """Read-only access to recordings saved before external uploads were retired."""
    with Session(request.app.state.engine) as session:
        record=session.get(db.RunAttachment,(run_id,attachment_id))
        if record is None: raise HTTPException(404,'RESULT_NOT_FOUND')
        return FileResponse(record.storage_path,media_type=record.document['media_type'],filename=record.document['name'])


@router.get('/api/control/v1/runs/{run_id}/events', dependencies=[Depends(admin)])
def inspect_events(run_id: str, request: Request):
    with Session(request.app.state.engine) as session:
        if session.get(db.Run, run_id) is None:
            raise HTTPException(404, 'RESULT_NOT_FOUND')
        events = session.scalars(select(db.Event).where(db.Event.run_id == run_id).order_by(db.Event.sequence))
        return {'request_id': request.state.request_id, 'events': [e.document for e in events]}
