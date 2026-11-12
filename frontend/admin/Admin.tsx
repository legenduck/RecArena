import {useState} from 'react';
import type {PolicyDefinition} from '../generated/control';
import type {Environment,PreparedArtifact,EntrySettings} from './types';
import {adminClient} from './api';
import {EnvironmentEditor} from './EnvironmentEditor';
import {DataModels,HistoryImport} from './CatalogManagement';
import {SavedComparisons} from './SavedComparisons';
import {PolicyMappings} from './PolicyMappings';
import {EntryUrlDialog} from './EntryUrlDialog';
import {UserProfiles} from './UserProfiles';
import {RolloutRecords} from './RolloutRecords';

const tabs=[{id:'environments',label:'Environments'},{id:'users',label:'User profiles'},{id:'data',label:'Product data'},{id:'rollouts',label:'Rollouts & results'}] as const;
type AdminTab=typeof tabs[number]['id'];

export default function Admin() {
  const [token,setToken] = useState('');
  const [connected,setConnected] = useState(false);
  const [environments,setEnvironments] = useState<Environment[]>([]);
  const [entrySettings,setEntrySettings] = useState<EntrySettings|null>(null);
  const [artifactOptions,setArtifactOptions] = useState<PreparedArtifact[]>([]);
  const [policies,setPolicies] = useState<PolicyDefinition[]>([]);
  const [message,setMessage] = useState('');
  const [busy,setBusy] = useState(false);
  const [tab,setTab] = useState<AdminTab>('environments');
  const [urlDialogOpen,setUrlDialogOpen] = useState(false);

  const {request,downloadExport,downloadAttachment}=adminClient(token);
  async function connect() {
    setBusy(true);setMessage('');
    try {
      const [list,definitions,artifacts,settings]=await Promise.all([request<{environments:Environment[]}>('/environments'),request<{policies:PolicyDefinition[]}>('/policies'),request<{artifacts:PreparedArtifact[]}>('/artifacts'),request<EntrySettings>('/site-settings')]);
      const values=list.environments.filter(e=>e.presentation);
      setEnvironments(values);setPolicies(definitions.policies);setArtifactOptions(artifacts.artifacts);setEntrySettings(settings);setConnected(true);
    } catch(error) {setMessage((error as Error).message);} finally {setBusy(false);}
  }
  return <div className={`admin-shell${connected ? '' : ' admin-shell--entry'}`}>
    <header className="admin-header"><span className="admin-brand">RecArena</span><span className="admin-context">Admin</span></header>
    <main className={`admin${connected ? '' : ' admin--entry'}`}>
    <section className={connected ? 'admin-overview' : 'admin-login-panel'} aria-labelledby="admin-title">
      <div className="admin-intro"><h1 id="admin-title">Admin console</h1>
        <p id="admin-description">Configure fixed research environments and inspect readiness.</p>
      </div>
      {connected && <button type="button" className="admin-create-url" aria-haspopup="dialog" onClick={()=>setUrlDialogOpen(true)}>Create entry URL</button>}
      {!connected && <form className="admin-login" aria-busy={busy} onSubmit={e=>{e.preventDefault();void connect();}}>
        <label htmlFor="admin-token">Administrator token</label>
        <div className="admin-login-controls">
          <input id="admin-token" type="password" value={token} placeholder="Enter your token" aria-describedby="admin-description" autoComplete="off" onChange={e=>setToken(e.target.value)} required/>
          <button type="submit" disabled={busy}>Connect</button>
        </div>
      </form>}
      {!connected && message && <p className="admin-entry-message" role="status">{message}</p>}
    </section>
    {connected && <>
      <nav className="admin-tabs" role="tablist" aria-label="Research console" onKeyDown={event=>{
        const index=tabs.findIndex(item=>item.id===tab);
        const next=event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
        if(next===null)return;
        event.preventDefault();setTab(tabs[next].id);document.getElementById(`tab-${tabs[next].id}`)?.focus();
      }}>
        {tabs.map(item=><button key={item.id} id={`tab-${item.id}`} role="tab" type="button" aria-selected={tab===item.id} aria-controls={`panel-${item.id}`} tabIndex={tab===item.id?0:-1} onClick={()=>setTab(item.id)}>{item.label}</button>)}
      </nav>
      <section id="panel-environments" role="tabpanel" aria-labelledby="tab-environments" hidden={tab!=='environments'}>
      <div className="admin-page-heading"><h2>Environments</h2><p>Inspect saved shopping conditions, create new versions and connect them to entry policy names.</p></div>
      {entrySettings && <PolicyMappings request={request} environments={environments} settings={entrySettings} onSaved={setEntrySettings}/>}
      <EnvironmentEditor request={request} environments={environments} setEnvironments={setEnvironments}
        artifactOptions={artifactOptions} setArtifactOptions={setArtifactOptions} policies={policies}/>

      </section>
      <section id="panel-users" role="tabpanel" aria-labelledby="tab-users" hidden={tab!=='users'}>
        <div className="admin-page-heading"><h2>User profiles</h2><p>Research users identify the fixed history used for personalization. A profile can be used by several independent browser sessions.</p></div>
        <UserProfiles request={request} environments={environments}/>
        <HistoryImport request={request}/>
      </section>
      <section id="panel-data" role="tabpanel" aria-labelledby="tab-data" hidden={tab!=='data'}>
        <div className="admin-page-heading"><h2>Product data</h2><p>Manage the catalog, reviews and user history used by your environments.</p></div>
        <DataModels request={request} artifacts={artifactOptions} onArtifactsChanged={setArtifactOptions}/>
      </section>
      <section id="panel-rollouts" role="tabpanel" aria-labelledby="tab-rollouts" hidden={tab!=='rollouts'}>
        <div className="admin-page-heading"><h2>Rollouts &amp; results</h2><p>Inspect shopping sessions, confirmed purchases and event logs. Export records for analysis.</p></div>
        <RolloutRecords request={request} environments={environments} downloadExport={downloadExport} downloadAttachment={downloadAttachment}/>
        <SavedComparisons request={request} downloadExport={downloadExport}/>
      </section>
      {entrySettings && <EntryUrlDialog settings={entrySettings} open={urlDialogOpen} onClose={()=>setUrlDialogOpen(false)}/>}
    </>}
  </main></div>;
}
