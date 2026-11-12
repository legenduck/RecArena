import {useState} from 'react';
import type {Request,PreparedArtifact} from './types';
import {useOperation} from './useOperation';
function DataRegistration({request,kind,onRegistered}:{request:Request;kind:'catalog'|'history';onRegistered?:()=>Promise<void>}) {
  const [text,setText]=useState('');
  const {message,setMessage,busy,execute}=useOperation();
  const path={catalog:'/catalogs/import',history:'/users/import'}[kind];
  const explanation={
    catalog:'Register a prepared catalog using a bundle_path under the prepared artifact directory.',
    history:'Register a fixed history snapshot with catalog ID, user IDs, recorded interactions and provenance.',
  }[kind];
  return <form onSubmit={e=>{e.preventDefault();void execute(async()=>{
    await request(path,'POST',JSON.parse(text));await onRegistered?.();setMessage('Prepared data registered.');
  });}}>
    <p className="admin-hint">{explanation}</p>
    <label className="wide">Registration JSON<textarea aria-label="Registration JSON" rows={8} value={text} onChange={e=>setText(e.target.value)} required/></label>
    <button disabled={busy}>{kind==='catalog'?'Import catalog':'Register data'}</button>
    {message && <p role="status">{message}</p>}
  </form>;
}

const artifactNames:Record<string,string>={catalog_snapshot:'Product catalog',review_snapshot:'Product reviews',history_snapshot:'User history'};

export function DataModels({request,artifacts,onArtifactsChanged}:{request:Request;artifacts:PreparedArtifact[];onArtifactsChanged:(artifacts:PreparedArtifact[])=>void}) {
  const {message,setMessage,busy,execute}=useOperation();
  async function refresh() {onArtifactsChanged((await request<{artifacts:PreparedArtifact[]}>('/artifacts')).artifacts);}
  return <>
    <section className="admin-card" aria-labelledby="available-data-title" data-testid="artifact-management">
      <div className="admin-section-heading"><div><h3 id="available-data-title">Available product data</h3>
        <p className="admin-hint">Catalog, reviews and user history available to environments.</p></div>
        <button type="button" disabled={busy} onClick={()=>void execute(refresh)}>Refresh status</button>
      </div>
      <p className="admin-resource-count">{artifacts.filter(a=>a.ready).length} of {artifacts.length} resources ready</p>
      {message && <p role="status">{message}</p>}
      {!artifacts.length?<p className="admin-empty-state">No data or service resources have been reported yet.</p>:<div className="table-scroll admin-resource-table" tabIndex={0} role="region" aria-label="Available product data"><table><thead><tr><th>Dataset</th><th>Status</th><th>Registration</th><th>Details</th></tr></thead><tbody>{artifacts.map(a=><tr key={a.manifest.artifact_id}>
        <td><strong>{artifactNames[a.manifest.artifact_type]??a.manifest.artifact_type}</strong><span className="admin-secondary-value">{a.manifest.artifact_id}</span></td>
        <td><span className={'admin-availability '+(a.ready?'admin-availability--ready':'admin-availability--unavailable')}>{a.ready?'Ready':'Not ready'}</span></td>
        <td>{a.registered?'Recorded metadata':'Reported by server'}</td>
        <td><details><summary>Version &amp; provenance</summary><pre>{JSON.stringify(a.manifest,null,2)}</pre></details></td>
      </tr>)}</tbody></table></div>}
      <p className="admin-hint">Recommendation policies are selected in Environments. Prepare their implementation and data in your recommendation service.</p>
    </section>
    <section className="admin-card" aria-labelledby="register-catalog-title"><h3 id="register-catalog-title">Register product data</h3>
      <p className="admin-hint">Import a prepared catalog into the platform for use by new environments.</p>
      <details className="admin-registration"><summary>Import a prepared catalog</summary><DataRegistration request={request} kind="catalog" onRegistered={refresh}/></details>
    </section>
  </>;
}

export function HistoryImport({request}:{request:Request}) {
  return <section className="admin-card"><h3>History data</h3><details><summary>Register prepared user history</summary><DataRegistration request={request} kind="history"/></details></section>;
}
