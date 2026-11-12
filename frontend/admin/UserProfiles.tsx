import {useState} from 'react';
import type {Environment,Request} from './types';
import {environmentLabel} from './environmentLabel';
type User={user_id:string;interaction_count:number;eligible_configured_policies:string[]|null};
type History={user_id:string;has_more:boolean;interactions:Array<{product_id:string;title:string;timestamp_utc:string;interaction:unknown}>};
export function UserProfiles({request,environments}:{request:Request;environments:Environment[]}) {
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const snapshots=[...new Set(environments.map(e=>e.history_snapshot_id))];
  const [snapshotId,setSnapshotId]=useState('');
  const historyId=snapshots.includes(snapshotId)?snapshotId:snapshots[0];
  const [supportEnvironment,setSupportEnvironment]=useState('');
  const [users,setUsers]=useState<User[]>([]);
  const [userQuery,setUserQuery]=useState('');
  const [userOffset,setUserOffset]=useState(0);
  const [history,setHistory]=useState<History|null>(null);
  const [historyOffset,setHistoryOffset]=useState(0);
  function reset() {setUsers([]);setHistory(null);setUserOffset(0);setHistoryOffset(0);}
  async function execute(action:()=>Promise<void>) {
    setBusy(true);setMessage('');
    try {await action();} catch(e) {setMessage((e as Error).message);} finally {setBusy(false);}
  }
  async function loadUsers(offset=0) {
    if (!historyId) return;
    const q=new URLSearchParams({...(supportEnvironment?{environment_version_id:supportEnvironment}:{}),history_snapshot_id:historyId,query:userQuery,offset:String(offset),limit:'50'});
    setUsers((await request<{users:User[]}>('/users?'+q)).users);setUserOffset(offset);
  }
  async function loadHistory(user:string,offset=0) {
    if (!historyId) return;
    const q=new URLSearchParams({history_snapshot_id:historyId,offset:String(offset),limit:'20'});
    setHistory(await request<History>(`/users/${encodeURIComponent(user)}/history?${q}`));setHistoryOffset(offset);
  }
  return <section className="admin-card" aria-labelledby="user-history-title"><h3 id="user-history-title">Research users and fixed history</h3>
      {message && <p role="status">{message}</p>}
      <label htmlFor="profile-history">History snapshot</label><select id="profile-history" disabled={busy} value={historyId??''} onChange={e=>{setSnapshotId(e.target.value);setSupportEnvironment('');reset();}}>
        {!snapshots.length && <option value="">No history available</option>}{snapshots.map(id=><option key={id}>{id}</option>)}
      </select>
      <label htmlFor="profile-environment">Check policy support in</label><select id="profile-environment" disabled={busy} value={supportEnvironment} onChange={e=>{setSupportEnvironment(e.target.value);reset();}}>
        <option value="">History only</option>{environments.filter(e=>e.history_snapshot_id===historyId).map(e=><option key={e.id} value={e.id}>{environmentLabel(e,environments)}</option>)}
      </select>
      <p className="admin-hint">Choose a history snapshot and find a research user. Policy support is checked only for the selected environment.</p>
      <form className="admin-search" onSubmit={e=>{e.preventDefault();setHistory(null);void execute(()=>loadUsers());}}><label>User ID prefix<input value={userQuery} onChange={e=>setUserQuery(e.target.value)}/></label><button disabled={busy||!historyId}>Find users</button></form>
      <div className="table-scroll"><table><thead><tr><th>User</th><th>Past interactions</th><th>Available configured policies</th><th>Actions</th></tr></thead><tbody>{users.map(u=><tr key={u.user_id}><td>{u.user_id}</td><td>{u.interaction_count}</td><td>{u.eligible_configured_policies===null?'Not checked':u.eligible_configured_policies.join(', ')||'None'}</td><td><button disabled={busy} onClick={()=>void execute(()=>loadHistory(u.user_id))}>View history</button></td></tr>)}</tbody></table></div>
      <button disabled={busy||userOffset===0} onClick={()=>void execute(()=>loadUsers(Math.max(0,userOffset-50)))}>Previous users</button>
      <button disabled={busy||users.length<50} onClick={()=>void execute(()=>loadUsers(userOffset+50))}>Next users</button>
      {history && <><h3>History for {history.user_id}</h3><div className="table-scroll"><table><thead><tr><th>Product</th><th>Time</th><th>Recorded interaction</th></tr></thead><tbody>
        {history.interactions.map((i,index)=><tr key={index}><td>{i.title}<br/>{i.product_id}</td><td>{i.timestamp_utc}</td><td><pre>{JSON.stringify(i.interaction,null,2)}</pre></td></tr>)}
      </tbody></table></div><button disabled={busy||historyOffset===0} onClick={()=>void execute(()=>loadHistory(history.user_id,historyOffset-20))}>Previous history</button>
        <button disabled={busy||!history.has_more} onClick={()=>void execute(()=>loadHistory(history.user_id,historyOffset+20))}>Next history</button></>}
    </section>;
}
