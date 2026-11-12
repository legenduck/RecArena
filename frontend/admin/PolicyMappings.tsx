import {useEffect,useState} from 'react';
import type {Request,Environment,EntrySettings} from './types';
import {environmentLabel} from './environmentLabel';
type EntryProps={request:Request;environments:Environment[];settings:EntrySettings;onSaved:(settings:EntrySettings)=>void};
type PolicyBinding={name:string;environment:string};
const bindingsOf=(settings:EntrySettings):PolicyBinding[]=>Object.entries(settings.policies).map(([name,environment])=>({name,environment}));
const orderedBindings=(bindings:PolicyBinding[])=>JSON.stringify(bindings.map(b=>[b.name,b.environment]).sort(([a],[b])=>a.localeCompare(b)));

export function PolicyMappings({request,environments,settings,onSaved}:EntryProps) {
  const [bindings,setBindings]=useState(()=>bindingsOf(settings));
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const published=environments.filter(e=>e.state==='PUBLISHED');
  const dirty=orderedBindings(bindings)!==orderedBindings(bindingsOf(settings));
  useEffect(()=>{setBindings(bindingsOf(settings));},[settings.policies]);

  function edit(values:PolicyBinding[]) {setBindings(values);setMessage('');setError('');}
  function discard() {setBindings(bindingsOf(settings));setMessage('Unsaved URL mapping changes discarded.');setError('');}
  async function save() {
    if(busy||!dirty)return;
    setError('');setMessage('');
    if(new Set(bindings.map(b=>b.name)).size!==bindings.length) {setError('URL policy names must be unique.');return;}
    if(bindings.some(b=>!b.name||!b.environment)) {setError('Each URL policy name needs a published environment.');return;}
    setBusy(true);
    try {
      const result=await request<Pick<EntrySettings,'default_environment_id'|'policies'>>('/site-settings','PUT',{
        default_environment_id:settings.default_environment_id,
        policies:Object.fromEntries(bindings.map(b=>[b.name,b.environment])),
      });
      const saved={...settings,...result};
      setBindings(bindingsOf(saved));onSaved(saved);setMessage('URL mappings saved.');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section id="policy-mappings" className="admin-card" aria-labelledby="policy-mappings-title">
    <h3 id="policy-mappings-title">URL policy mappings</h3>
    <p className="admin-hint">Choose which published environment each policy name in an entry URL uses. Existing rollouts keep their assigned environment.</p>
    <form onSubmit={e=>{e.preventDefault();void save();}} aria-busy={busy}>
      <fieldset className="admin-edit-fields" disabled={busy}>
        <legend className="admin-visually-hidden">URL policy mappings</legend>
        <div className="table-scroll"><table><thead><tr><th>Policy name in URL</th><th>Published environment</th><th>Actions</th></tr></thead><tbody>
          {bindings.map((binding,index)=><tr key={index}>
            <td><input aria-label={'URL policy name '+(index+1)} value={binding.name} required onChange={e=>edit(bindings.map((v,i)=>i===index?{...v,name:e.target.value}:v))}/></td>
            <td><select aria-label={'Policy environment '+(index+1)} value={binding.environment} required onChange={e=>edit(bindings.map((v,i)=>i===index?{...v,environment:e.target.value}:v))}>
              <option value="">Select environment</option>{published.map(e=><option key={e.id} value={e.id}>{environmentLabel(e,environments)}</option>)}
            </select></td><td><button type="button" className="admin-button-subtle" onClick={()=>edit(bindings.filter((_,i)=>i!==index))}>Remove</button></td>
          </tr>)}
        </tbody></table></div>
        {!bindings.length && <p className="admin-hint">No URL policy names configured.</p>}
        <button type="button" className="admin-button-subtle" onClick={()=>edit([...bindings,{name:'',environment:''}])}>Add policy name</button>
      </fieldset>
      <div className="admin-form-footer">
        <p className={'admin-edit-status'+(dirty?' admin-edit-status--unsaved':'')} role="status">{busy?'Saving URL mappings…':dirty?'Unsaved URL mapping changes':message||'URL mappings are saved.'}</p>
        <div className="actions">
          <button type="submit" className="admin-button-primary" disabled={busy||!dirty}>Save URL mappings</button>
          <button type="button" disabled={busy||!dirty} onClick={discard}>Discard changes</button>
        </div>
      </div>
      {error && <p role="alert" className="admin-form-error">{error}</p>}
    </form>
  </section>;
}
