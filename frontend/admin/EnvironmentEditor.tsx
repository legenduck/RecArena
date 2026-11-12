import {useState} from 'react';
import {uuid} from '../shared/uuid';
import type {EnvironmentBindings,GridBlock,PagedRowBlock,PolicyConfig,Presentation,RankingSource,PolicyDefinition} from '../generated/control';
import type {Environment,PreparedArtifact,Request} from './types';
import {environmentLabel} from './environmentLabel';
import {EnvironmentSummary} from './EnvironmentSummary';
import {PolicyDiagnostics} from './PolicyDiagnostics';
function policyKey(policy:PolicyConfig) {return [policy.service_id??'default',policy.policy_id,policy.version].join('/');}
type Block = GridBlock | PagedRowBlock;
function presentationOf(environment:Environment):Presentation {
  return structuredClone(environment.presentation);
}

function bindingsOf(environment:Environment):EnvironmentBindings {
  return {catalog_snapshot_id:environment.dataset_snapshot_id,review_snapshot_id:environment.review_snapshot_id,
    history_snapshot_id:environment.history_snapshot_id};
}


export function EnvironmentEditor({request,environments,setEnvironments,artifactOptions,setArtifactOptions,policies}:{
 request:Request; environments:Environment[]; setEnvironments:React.Dispatch<React.SetStateAction<Environment[]>>;
 artifactOptions:PreparedArtifact[];setArtifactOptions:(items:PreparedArtifact[])=>void;policies:PolicyDefinition[];
}) {
  const [environment,setEnvironment] = useState<Environment|null>(environments.at(-1)??null);
  const [presentation,setPresentation] = useState<Presentation|null>(environment?presentationOf(environment):null);
  const [bindings,setBindings] = useState<EnvironmentBindings|null>(environment?bindingsOf(environment):null);
  const [copying,setCopying] = useState(false);
  const [user,setUser] = useState('');
  const [message,setMessage] = useState('');
  const [actionFailed,setActionFailed] = useState(false);
  const [busy,setBusy] = useState(false);
  function select(value:Environment) {setEnvironment(value);setPresentation(presentationOf(value));setBindings(bindingsOf(value));setCopying(false);}
  function startCopy() {
    if (!environment || busy) return;
    setPresentation(presentationOf(environment));setBindings(structuredClone(bindingsOf(environment)));
    setCopying(true);setUser('');setMessage('');setActionFailed(false);
  }
  async function execute(action:()=>Promise<void>) {
    setBusy(true);setMessage('');setActionFailed(false);
    try {await action();} catch(e) {setActionFailed(true);setMessage((e as Error).message);} finally {setBusy(false);}
  }
  function updateSource(id:string,source:RankingSource) {
    setPresentation(p=>p && {...p,ranking_sources:{...p.ranking_sources,[id]:source}});
  }
  function updateBlock(index:number,block:Block) {
    setPresentation(p=>p && {...p,layout:{...p.layout,blocks:p.layout.blocks.map((b,i)=>i===index?block:b)}});
  }
  function moveBlock(index:number,offset:number) {
    setPresentation(p=>{
      if (!p) return p;
      const blocks=[...p.layout.blocks];
      [blocks[index],blocks[index+offset]]=[blocks[index+offset],blocks[index]];
      return {...p,layout:{...p.layout,blocks}};
    });
  }
  async function save() {
    await execute(async()=>{
      if (!environment || !presentation || (environment.state==='PUBLISHED' && !copying)) return;
      const value=copying || JSON.stringify(bindings)!==JSON.stringify(bindingsOf(environment))
        ? await request<Environment>('/environments','POST',{base_environment_id:environment.id,presentation,bindings})
        : await request<Environment>(`/environments/${environment.id}/layout`,'PUT',{presentation});
      setEnvironments(values=>[...values.filter(v=>v.id!==value.id),value]);select(value);
      setMessage(copying?'New draft saved. Validate and publish it before linking it to a URL policy name.':'Draft saved.');
    });
  }
  async function transition(action:'validate'|'publish') {
    if (!environment || copying || environment.state==='PUBLISHED') return;
    await execute(async()=>{
      const value=await request<Environment>(`/environments/${environment!.id}/${action}`,'POST',{user_id:user});
      setEnvironments(values=>values.map(v=>v.id===value.id?value:v));select(value);setMessage(`Environment ${value.state.toLowerCase()}.`);
    });
  }
  const readOnly=environment?.state==='PUBLISHED' && !copying;
  const dirty=copying || !!(environment && presentation && !readOnly && (JSON.stringify(presentation)!==JSON.stringify(presentationOf(environment)) || JSON.stringify(bindings)!==JSON.stringify(bindingsOf(environment))));
  return <section id="environment-editor" className="admin-card" aria-labelledby="environment-editor-title">
      <h3 id="environment-editor-title">Environment details</h3>
      <p className="admin-hint">Inspect a saved environment or create a new version from it.</p>
      <label htmlFor="environment-version">Environment version</label><select id="environment-version" disabled={busy||dirty} value={environment?.id ?? ''} onChange={e=>{select(environments.find(v=>v.id===e.target.value)!);setMessage('');setActionFailed(false);}}>
        {environments.map(e=><option key={e.id} value={e.id}>{environmentLabel(e,environments)} · {e.state}</option>)}
      </select>
      {dirty && <p className="admin-hint">Save or discard your environment changes before selecting another version.</p>}
      {environment && presentation && <>
        <div className={'admin-environment-mode'+(copying?' admin-environment-mode--draft':'')}>
          <div><span className="admin-state-badge">{copying?'Unsaved draft':readOnly?'Published · Read only':environment.state}</span>
            <p>{copying?'Editing a copy. Save to create a separate environment version.':readOnly?'This version is fixed. Its settings stay with the rollouts collected using it.':'Edit this draft, then validate and publish the saved version.'}</p>
          </div>
          {readOnly && <button type="button" className="admin-button-primary" disabled={busy} onClick={startCopy}>Copy to new draft</button>}
        </div>
        <details><summary>{copying?'Source environment identifiers':'Environment identifiers'}</summary><p>Environment ID: <code>{environment.id}</code></p>
          <p>Catalog: {environment.dataset_snapshot_id}</p><p>History: {environment.history_snapshot_id}</p>
        </details>
        {readOnly?<EnvironmentSummary environment={environment} presentation={presentation}/>:<>
        <form onSubmit={e=>{e.preventDefault();if(!busy&&dirty)void save();}} aria-busy={busy}>
        <fieldset className="admin-edit-fields" disabled={busy}><legend className="admin-visually-hidden">Selected environment configuration</legend>
        <details><summary>Product data bindings</summary>
          <button type="button" disabled={busy} onClick={()=>execute(async()=>setArtifactOptions((await request<{artifacts:PreparedArtifact[]}>('/artifacts')).artifacts))}>Refresh available artifacts</button>
          {bindings && (['catalog_snapshot_id','review_snapshot_id','history_snapshot_id'] as const).map((key,index)=><label key={key}>{key}<select value={bindings[key]} onChange={e=>setBindings({...bindings,[key]:e.target.value})}>
            {artifactOptions.filter(a=>a.manifest.artifact_type===['catalog_snapshot','review_snapshot','history_snapshot'][index]).map(a=><option key={a.manifest.artifact_id} value={a.manifest.artifact_id}>{a.manifest.artifact_id} · {a.ready?'Ready':'Not ready'}</option>)}
          </select></label>)}
        </details>
        <h2>Ranking sources</h2>
        {Object.entries(presentation.ranking_sources).map(([id,source])=>{
          const available=policies.filter(p=>p.catalog_snapshot_id===bindings?.catalog_snapshot_id);
          const definition=available.find(p=>policyKey(p.policy)===policyKey(source.policy));
          return <fieldset key={id}><legend>Source {id}</legend>
            <label>Recommendation policy<select value={policyKey(source.policy)} onChange={e=>{
              const selected=available.find(p=>policyKey(p.policy)===e.target.value)!;
              updateSource(id,{policy:selected.policy,policy_version_id:uuid()});
            }}>
              {!definition && <option value={policyKey(source.policy)}>{source.policy.policy_id} · unavailable</option>}
              {available.map(p=><option key={policyKey(p.policy)} value={policyKey(p.policy)}>{p.name} · {p.policy.service_id} · {p.policy.version}</option>)}
            </select></label>
            <p>{definition?.description}</p>
            <dl className="admin-setting-list">
              <div><dt>Service</dt><dd>{source.policy.service_id}</dd></div>
              <div><dt>Policy</dt><dd>{source.policy.policy_id}</dd></div>
              <div><dt>Version</dt><dd>{source.policy.version}</dd></div>
            </dl>
            <button type="button" disabled={presentation.layout.blocks.some(b=>b.source===id)} onClick={()=>setPresentation(p=>{
              if (!p) return p;const sources={...p.ranking_sources};delete sources[id];return {...p,ranking_sources:sources};
            })}>Remove source {id}</button>
          </fieldset>;
        })}
        <button type="button" onClick={()=>{const id='source_'+uuid().slice(0,8);updateSource(id,structuredClone(Object.values(presentation.ranking_sources)[0]));}}>Add ranking source</button>
        <h2 id="layout">Layout / Sections</h2>
        <label className="admin-sidebar-toggle"><input type="checkbox" checked={presentation.layout.cart_enabled??false}
          onChange={e=>setPresentation({...presentation,layout:{...presentation.layout,cart_enabled:e.target.checked}})}/>Enable shopping cart</label>
        <p className="admin-hint">Off by default. When enabled, shoppers can add items, adjust quantities and purchase their cart, or use Buy now for one product. New sessions use the published setting.</p>
        <label className="admin-sidebar-toggle"><input type="checkbox" checked={presentation.layout.abandon_enabled??false}
          onChange={e=>setPresentation({...presentation,layout:{...presentation.layout,abandon_enabled:e.target.checked}})}/>Show Abandon shopping button</label>
        <p className="admin-hint">Off by default. When enabled, shoppers can explicitly end shopping without a purchase.</p>
        <label className="admin-sidebar-toggle"><input type="checkbox" checked={presentation.layout.sidebar_enabled??false}
          onChange={e=>setPresentation({...presentation,layout:{...presentation.layout,sidebar_enabled:e.target.checked}})}/>Show search filter sidebar</label>
        <p className="admin-hint">Price and rating filters apply within the retrieved candidates and preserve their ranking order.</p>
        <label>Main page size<input type="number" min={1} value={presentation.layout.main_page_size} onChange={e=>setPresentation({...presentation,layout:{...presentation.layout,main_page_size:Number(e.target.value)}})}/></label>
        {presentation.layout.blocks.map((block,index)=><fieldset key={index}><legend>Section {index+1}</legend>
          <label>Section ID<input value={block.id} onChange={e=>updateBlock(index,{...block,id:e.target.value})}/></label>
          <label>Title<input value={block.title} onChange={e=>updateBlock(index,{...block,title:e.target.value})}/></label>
          <label>Ranking source<select value={block.source} onChange={e=>updateBlock(index,{...block,source:e.target.value})}>{Object.keys(presentation.ranking_sources).map(id=><option key={id}>{id}</option>)}</select></label>
          <label>Component<select value={block.component} onChange={e=>{
            const base={id:block.id,title:block.title,source:block.source,offset:0,visibility:block.visibility};
            updateBlock(index,e.target.value==='grid'?{...base,component:'grid',count:10,columns:4}:{...base,component:'paged_row',total_count:20,visible_count:5});
          }}><option value="grid">Grid</option><option value="paged_row">Paged row</option></select></label>
          <label>Offset<input type="number" min={0} value={block.offset ?? 0} onChange={e=>updateBlock(index,{...block,offset:Number(e.target.value)})}/></label>
          {block.component==='paged_row' ? <>
            <label>Total item count<input type="number" min={1} value={block.total_count} onChange={e=>updateBlock(index,{...block,total_count:Number(e.target.value)})}/></label>
            <label>Visible item count<input type="number" min={1} value={block.visible_count} onChange={e=>updateBlock(index,{...block,visible_count:Number(e.target.value)})}/></label>
          </> : <>
            <label>Item count<input type="number" min={1} value={(block as GridBlock).count} onChange={e=>updateBlock(index,{...block as GridBlock,count:Number(e.target.value)})}/></label>
            <label>Columns<input type="number" min={1} max={12} value={(block as GridBlock).columns} onChange={e=>updateBlock(index,{...block as GridBlock,columns:Number(e.target.value)})}/></label>
          </>}
          <label>Page visibility<select value={block.visibility} onChange={e=>updateBlock(index,{...block,visibility:e.target.value as 'all_pages'|'first_page'})}><option value="all_pages">All pages</option><option value="first_page">First page</option></select></label>
          <div className="actions"><button type="button" disabled={index===0} onClick={()=>moveBlock(index,-1)}>Move up</button><button type="button" disabled={index===presentation.layout.blocks.length-1} onClick={()=>moveBlock(index,1)}>Move down</button>
            <button type="button" disabled={presentation.layout.blocks.length===1} onClick={()=>setPresentation({...presentation,layout:{...presentation.layout,blocks:presentation.layout.blocks.filter((_,i)=>i!==index)}})}>Remove section</button></div>
        </fieldset>)}
        <button type="button" onClick={()=>setPresentation({...presentation,layout:{...presentation.layout,blocks:[...presentation.layout.blocks,
          {id:'block_'+uuid().slice(0,8),source:Object.keys(presentation.ranking_sources)[0],title:'Related products',component:'paged_row',offset:0,total_count:20,visible_count:5,visibility:'first_page'}]}})}>Add section</button>
        <div className="admin-form-footer">
          <p className={'admin-edit-status'+(dirty?' admin-edit-status--unsaved':'')} role="status">{copying?'New draft has not been saved.':dirty?'Unsaved environment changes':'Environment changes are saved.'}</p>
          <div className="actions"><button type="submit" className="admin-button-primary" disabled={!dirty}>{copying?'Save new draft':'Save environment draft'}</button>
            <button type="button" disabled={!dirty} onClick={()=>{select(environment);setActionFailed(false);setMessage(copying?'Copy discarded. No new environment was saved.':'Unsaved environment changes discarded.');}}>{copying?'Discard copy':'Discard changes'}</button></div>
        </div>
        {!copying && <section className="admin-publish-panel" aria-labelledby="publish-environment-title">
          <h4 id="publish-environment-title">Validate and publish saved version</h4>
          <p className="admin-hint">Validate the saved environment for a research user, then publish it to make it available for URL mappings.</p>
          <label>Validation user ID<input value={user} onChange={e=>setUser(e.target.value)}/></label>
          <div className="actions"><button type="button" disabled={!!dirty || !user || environment.state==='PUBLISHED'} onClick={()=>transition('validate')}>Validate environment</button>
            <button type="button" className={environment.state==='VALIDATED'?'admin-button-primary':undefined} disabled={!!dirty || !user || environment.state!=='VALIDATED'} onClick={()=>transition('publish')}>Publish environment</button></div>
        </section>}
        </fieldset>
        </form>
        </>}
        {message && (actionFailed||!dirty) && <p role={actionFailed?'alert':'status'} className={actionFailed?'admin-form-error':'admin-action-message'}>{message}</p>}
        <PolicyDiagnostics request={request} environment={environment} environments={environments} hasUnsavedChanges={dirty}/>
      </>}
      {!environment && <p>No prepared environments are available.</p>}
      </section>;
}
