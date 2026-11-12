import {useEffect,useState} from 'react';
import type {Request,Environment} from './types';
import {environmentLabel} from './environmentLabel';
import {useOperation} from './useOperation';
type RankedItem={product_id:string;retrieval_rank:number;final_rank:number;final_score:number|null;score_components:Record<string,number|null>;signal_missing_flags:Record<string,boolean>};
type Diagnostic={ranking:{ranked_items:RankedItem[];provenance:unknown;diagnostics:unknown}};

export function PolicyDiagnostics({request,environment,environments,hasUnsavedChanges}:{request:Request;environment:Environment|null;environments:Environment[];hasUnsavedChanges:boolean}) {
  const {message,setMessage,busy,execute}=useOperation();
  const [query,setQuery]=useState('');
  const [diagnosticUser,setDiagnosticUser]=useState('');
  const [source,setSource]=useState('main');
  const [diagnostic,setDiagnostic]=useState<{environmentId:string;environmentName:string;userId:string;query:string;result:Diagnostic}|null>(null);
  const sources=Object.keys(environment?.presentation.ranking_sources??{main:{}});
  useEffect(()=>{setDiagnostic(null);setMessage('');},[environment?.id,environment?.config]);
  return <details className="admin-environment-diagnostics" data-testid="policy-diagnostics"><summary>Test recommendations</summary>
      <p className="admin-hint">Run a search to inspect item rankings and scores. This test creates no rollout.</p>
      <p className="admin-diagnostic-context"><span>Saved environment</span><strong>{environment?environmentLabel(environment,environments):'None selected'}</strong></p>
      {hasUnsavedChanges && <p className="admin-hint">Save your draft before testing its recommendations.</p>}
      {message && <p role="status">{message}</p>}
      <form onSubmit={e=>{e.preventDefault();if(!environment||hasUnsavedChanges||busy)return;const environmentId=environment.id;void execute(async()=>{
        const result=await request<Diagnostic>('/policies/diagnostics','POST',{environment_version_id:environmentId,user_id:diagnosticUser,source_id:sources.includes(source)?source:sources[0],query});
        setDiagnostic({environmentId,environmentName:environmentLabel(environment,environments),userId:diagnosticUser,query,result});
      });}}>
        <fieldset className="admin-edit-fields" disabled={busy||hasUnsavedChanges||!environment}><legend className="admin-visually-hidden">Recommendation test inputs</legend>
        <div className="admin-form-grid"><label>Research user ID<input value={diagnosticUser} onChange={e=>setDiagnosticUser(e.target.value)} required/></label>
        <label>Ranking source<select aria-label="Ranking source" value={sources.includes(source)?source:sources[0]} onChange={e=>setSource(e.target.value)}>{sources.map(s=><option key={s}>{s}</option>)}</select></label>
        <label>Search query<input value={query} onChange={e=>setQuery(e.target.value)} required/></label></div><button disabled={!diagnosticUser}>Run recommendation test</button>
        </fieldset>
      </form>
      {diagnostic && <><p>Result for {diagnostic.environmentName} · {diagnostic.userId} · {diagnostic.query}</p>
        <details><summary>Diagnostic environment ID</summary><code>{diagnostic.environmentId}</code></details>
        <pre>{JSON.stringify({provenance:diagnostic.result.ranking.provenance,diagnostics:diagnostic.result.ranking.diagnostics},null,2)}</pre>
        <div className="table-scroll"><table><thead><tr><th>Product</th><th>Retrieval rank</th><th>Final rank</th><th>Final score</th><th>Components</th></tr></thead><tbody>{diagnostic.result.ranking.ranked_items.map(i=><tr key={i.product_id}><td>{i.product_id}</td><td>{i.retrieval_rank}</td><td>{i.final_rank}</td><td>{i.final_score}</td><td><details><summary>Scores and flags</summary><pre>{JSON.stringify({scores:i.score_components,flags:i.signal_missing_flags},null,2)}</pre></details></td></tr>)}</tbody></table></div>
      </>}
    </details>;
}
