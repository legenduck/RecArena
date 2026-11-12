import {useEffect,useRef,useState} from 'react';
import type {EntrySettings} from './types';
export function EntryUrlDialog({settings,open,onClose}:{settings:EntrySettings;open:boolean;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [user,setUser]=useState('');
  const [policy,setPolicy]=useState('');
  const [agent,setAgent]=useState('');
  const [url,setUrl]=useState('');
  const [copyMessage,setCopyMessage]=useState('');
  function clearUrl(){setUrl('');setCopyMessage('');}
  useEffect(()=>{clearUrl();setPolicy(value=>value in settings.policies?value:'');},[settings.policies]);
  useEffect(()=>{
    const element=dialog.current;
    if(open&&!element?.open)element?.showModal();
    else if(!open&&element?.open)element.close();
  },[open]);
  async function copyUrl(){
    try{await navigator.clipboard.writeText(url);setCopyMessage('URL copied.');}
    catch{setCopyMessage('Copy unavailable. Select the URL above and copy it manually.');}
  }
  return <dialog ref={dialog} id="entry-url-tools" className="admin-card admin-url-dialog" aria-labelledby="entry-url-tools-title" aria-describedby="entry-url-description" onCancel={onClose} onClose={onClose} onKeyDown={event=>{
    if(event.key!=='Tab')return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary')).filter(el=>el.getClientRects().length>0);
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }}>
    <div className="admin-dialog-heading"><h2 id="entry-url-tools-title">Create entry URL</h2><button type="button" className="admin-dialog-close" aria-label="Close URL builder" onClick={onClose}><span aria-hidden="true">×</span></button></div>
    <p id="entry-url-description" className="admin-hint">Choose a research user and a saved policy name. Opening the generated URL starts or resumes a rollout.</p>
    <div className="admin-url-format"><strong>Plain URL</strong><span>User and policy settings are visible in the address.</span></div>
      <form onSubmit={e=>{e.preventDefault();const value=new URL(settings.shop_url);value.search=new URLSearchParams({user_id:user,policy,...(agent?{agent}:{})}).toString();setUrl(value.toString());setCopyMessage('');}}>
        <div className="admin-form-grid">
          <label>User ID<input autoFocus value={user} onChange={e=>{setUser(e.target.value);clearUrl();}} required/></label>
          <label htmlFor="entry-url-policy">Policy name in URL<select id="entry-url-policy" aria-label="Policy name in URL" value={policy} onChange={e=>{setPolicy(e.target.value);clearUrl();}} required>
            <option value="">Select saved policy name</option>{Object.keys(settings.policies).map(name=><option key={name}>{name}</option>)}
          </select></label>
          <label>Agent label (optional)<input value={agent} onChange={e=>{setAgent(e.target.value);clearUrl();}}/></label>
        </div>
        <button type="submit" className="admin-button-primary" disabled={!Object.keys(settings.policies).length}>Generate URL</button>
        {!Object.keys(settings.policies).length && <p className="admin-hint">Save a policy name in the Environments tab before creating an entry URL.</p>}
      </form>
      {url && <div className="admin-generated-url"><label htmlFor="generated-entry-url">Generated entry URL</label><textarea id="generated-entry-url" rows={3} readOnly value={url} onFocus={e=>e.currentTarget.select()}/>
        <div className="actions"><button type="button" onClick={()=>void copyUrl()}>Copy URL</button><a className="admin-text-link" href={url} target="_blank" rel="noreferrer">Open in new tab</a></div>
        {copyMessage && <p className="admin-copy-feedback" role="status">{copyMessage}</p>}
      </div>}
    <details className="admin-encrypted-help"><summary>Encrypted URL — generate locally</summary>
      <p className="admin-hint">To keep settings out of the readable address, use the local Python tool with the shared key configured for your shopping server.</p>
      <p className="admin-hint">Run <code>scripts/make_rollout_url.py</code> with <code>--format encrypted</code>. This dialog generates plain URLs; encrypted URLs are generated on your machine.</p>
    </details>
  </dialog>;
}
