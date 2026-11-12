import {useState} from 'react';
import type {Request} from './types';
import {useOperation} from './useOperation';
type Experiment={id:string;name:string;warnings:{condition:string;field:string;message:string}[]};
type Run={id:string;state:string;user_id:string;task_version_id:string|null;condition_id:string|null;repetition:number|null;seed:number|null};
export function SavedComparisons({request,downloadExport}:{request:Request;downloadExport:(id:string)=>Promise<void>}) {
  const {message,busy,execute}=useOperation();
  const [experiments,setExperiments]=useState<Experiment[]>([]);
  const [experiment,setExperiment]=useState<Experiment|null>(null);
  const [runs,setRuns]=useState<Run[]>([]);
  return <section className="admin-card"><details data-testid="saved-comparisons"><summary>Previously saved comparison records</summary>
    <p className="admin-hint">Read existing comparison settings, repetitions and seeds. New rollouts start through shopping entry URLs.</p>
    {message && <p role="status">{message}</p>}
    <button disabled={busy} onClick={()=>void execute(async()=>setExperiments((await request<{experiments:Experiment[]}>('/experiments')).experiments))}>Refresh saved comparisons</button>
    <label>Saved comparison<select disabled={busy} value={experiment?.id??''} onChange={e=>{setExperiment(experiments.find(x=>x.id===e.target.value)??null);setRuns([]);}}>
      <option value="">Select saved comparison</option>{experiments.map(e=><option key={e.id} value={e.id}>{e.name} · {e.id}</option>)}
    </select></label>
    {experiment && <>
      <details><summary>Original comparison settings</summary><pre>{JSON.stringify(experiment,null,2)}</pre></details>
      {experiment.warnings.length>0 && <ul>{experiment.warnings.map((w,i)=><li key={i}>{w.condition}: {w.field} — {w.message}</li>)}</ul>}
      <div className="actions">
        <button disabled={busy} onClick={()=>void execute(async()=>setRuns((await request<{runs:Run[]}>('/runs?experiment_id='+encodeURIComponent(experiment.id))).runs))}>View comparison rollouts</button>
        <button disabled={busy} onClick={()=>void execute(async()=>{const result=await request<{export_id:string}>('/exports','POST',{experiment_id:experiment.id});await downloadExport(result.export_id);})}>Export comparison records</button>
      </div>
      <div className="table-scroll"><table><thead><tr><th>Rollout</th><th>User / task</th><th>Condition</th><th>Repetition / seed</th><th>Status</th></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td>{r.id}</td><td>{r.user_id}<br/>{r.task_version_id}</td><td>{r.condition_id}</td><td>{r.repetition} / {r.seed}</td><td>{r.state}</td></tr>)}</tbody></table></div>
    </>}
  </details></section>;
}
