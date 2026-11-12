import {useState} from 'react';
import type {Environment,Request} from './types';
import {environmentLabel} from './environmentLabel';
import {RunTimeline,LoggedEvent,ResultRecords} from './RunTimeline';
type Run={id:string;user_id:string;requested_policy:string|null;agent_label:string|null;external_task_id:string|null;
  client_run_id:string|null;shop_session_id:string|null;state:string;started_at:string|null;ended_at:string|null;end_reason:string|null;
  created_at:string;first_interaction_at:string|null;recording_method:string|null;purchase_id:string|null;environment_version_id:string};
const filterNames=['run_id','user_id','requested_policy','applied_policy','agent_label','external_task_id','client_run_id','state','run_kind','recording_method'] as const;

type InspectionResults=ResultRecords & {attachments:{attachment_id:string;name:string;media_type:string;size_bytes:number}[];runner_telemetry:unknown};

export function RolloutRecords({request,environments,downloadExport,downloadAttachment}:{request:Request;environments:Environment[];downloadExport:(id:string)=>Promise<void>;downloadAttachment:(run:string,id:string,name:string)=>Promise<void>}) {
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const [runs,setRuns]=useState<Run[]>([]);
  const [filters,setFilters]=useState<Record<string,string>>({});
  const [inspection,setInspection]=useState<{id:string;run:unknown;results:InspectionResults;events:{events:LoggedEvent[]}}|null>(null);
  const [runTotal,setRunTotal]=useState(0);
  const [runOffset,setRunOffset]=useState(0);
  function appliedEnvironment(id:string) {const value=environments.find(e=>e.id===id);return value?environmentLabel(value,environments):'Environment '+id;}
  async function execute(action:()=>Promise<void>) {
    setBusy(true);setMessage('');
    try {await action();} catch(e) {setMessage((e as Error).message);} finally {setBusy(false);}
  }
  const activeFilters=()=>Object.fromEntries(Object.entries(filters).filter(([,value])=>value!==''));
  async function loadRuns(offset=0) {const result=await request<{runs:Run[];total:number}>('/runs?'+new URLSearchParams({...activeFilters(),offset:String(offset)}));setRuns(result.runs);setRunTotal(result.total);setRunOffset(offset);}

  return <section className="admin-card" aria-labelledby="rollout-records-title"><h3 id="rollout-records-title">Rollout records</h3>
      {message && <p role="status">{message}</p>}
      <form onSubmit={e=>{e.preventDefault();void execute(()=>loadRuns());}}><div className="admin-filter-grid">{filterNames.map(name=><label key={name}>{name}<input value={filters[name]??''} onChange={e=>setFilters({...filters,[name]:e.target.value})}/></label>)}</div><button disabled={busy}>Find rollouts</button></form>
      <p>Showing {runs.length} of {runTotal} matching rollouts. Exports include all matches, not only this page.</p>
      <button disabled={busy||runOffset===0} onClick={()=>void execute(()=>loadRuns(Math.max(0,runOffset-100)))}>Previous rollouts</button>
      <button disabled={busy||runOffset+runs.length>=runTotal} onClick={()=>void execute(()=>loadRuns(runOffset+100))}>Next rollouts</button>
      <button disabled={busy} onClick={()=>void execute(async()=>{const e=await request<{export_id:string}>('/exports','POST',{filters:activeFilters()});await downloadExport(e.export_id);})}>Export matching rollouts</button>
      <div className="table-scroll"><table><thead><tr><th>Rollout / session</th><th>User / policy</th><th>Labels</th><th>Status / time</th><th>Actions</th></tr></thead><tbody>{runs.map(r=><tr key={r.id}>
        <td>{r.id}<br/>{r.shop_session_id}</td><td>{r.user_id}<br/>{r.requested_policy}</td><td>{r.agent_label}<br/>{r.external_task_id}<br/>{r.client_run_id}</td>
        <td>{r.state} · {r.end_reason}<br/>Created: {r.created_at}<br/>First observed action: {r.first_interaction_at??'None recorded'}<br/>Ended: {r.ended_at??'Not ended'}<br/>Purchase: {r.purchase_id??'None confirmed'}<br/>Recording method: {r.recording_method??'Not recorded'}<br/>Applied environment: {appliedEnvironment(r.environment_version_id)}</td>
        <td className="admin-row-actions"><button disabled={busy} onClick={()=>void execute(async()=>{const [run,results,events]=await Promise.all([request(`/runs/${r.id}`),request<InspectionResults>(`/runs/${r.id}/results`),request<{events:LoggedEvent[]}>(`/runs/${r.id}/events`)]);setInspection({id:r.id,run,results,events});})}>Inspect rollout</button>
          <button disabled={busy||!['READY','RUNNING'].includes(r.state)} onClick={()=>void execute(async()=>{await request(`/runs/${r.id}/cancel`,'POST');await loadRuns();})}>End rollout</button>
          <button disabled={busy} onClick={()=>void execute(async()=>{const e=await request<{export_id:string}>('/exports','POST',{run_ids:[r.id]});await downloadExport(e.export_id);})}>Export rollout</button></td>
      </tr>)}</tbody></table></div>{inspection!==null && <><details open><summary>Requested and applied settings / results</summary><pre>{JSON.stringify({run:inspection.run,results:inspection.results},null,2)}</pre></details>
        {inspection.results.runner_telemetry!=null && <p>Archived external records (read only).</p>}
        {!!inspection.results.attachments?.length && <p>Archived recordings (read only):</p>}
        {(inspection.results.attachments??[]).map(a=><button key={a.attachment_id} disabled={busy} onClick={()=>void execute(()=>downloadAttachment(inspection.id,a.attachment_id,a.name))}>Download {a.name} ({a.media_type}, {a.size_bytes} bytes)</button>)}
        <RunTimeline events={inspection.events.events} records={inspection.results}/></>}
    </section>;
}
