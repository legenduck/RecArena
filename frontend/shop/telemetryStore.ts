import type {BrowserEvent} from '../generated/api';

type Record = {id?:number;session:string;eventId:string;event:BrowserEvent;state:'pending'|'rejected';reason?:string};

// This store contains only the site's outgoing events, scoped by the opaque URL session.
export class TelemetryStore {
  private opening:Promise<IDBDatabase>|undefined;
  constructor(private session:string) {}

  private open() {
    if (!this.opening) this.opening=new Promise<IDBDatabase>((resolve,reject)=>{
      const request=indexedDB.open('recarena-shopping-events',1);
      let blocked=false;
      request.onupgradeneeded=()=>{
        const store=request.result.createObjectStore('events',{keyPath:'id',autoIncrement:true});
        store.createIndex('identity',['session','eventId'],{unique:true});
        store.createIndex('state',['session','state']);
      };
      request.onsuccess=()=>{
        if(blocked){request.result.close();return;}
        request.result.onversionchange=()=>{this.opening=undefined;request.result.close();};
        resolve(request.result);
      };
      request.onerror=()=>reject(request.error);
      request.onblocked=()=>{blocked=true;reject(new Error('Event storage is blocked'));};
    }).catch(error=>{this.opening=undefined;throw error;});
    return this.opening;
  }

  close() {
    const opening=this.opening;
    this.opening=undefined;
    void opening?.then(database=>database.close(),()=>{});
  }

  private async transaction<T>(mode:IDBTransactionMode,action:(store:IDBObjectStore,result:(value:T)=>void)=>void) {
    const database=await this.open();
    return new Promise<T>((resolve,reject)=>{
      const transaction=database.transaction('events',mode);
      let value:T;
      transaction.oncomplete=()=>resolve(value);
      transaction.onerror=()=>reject(transaction.error);
      transaction.onabort=()=>reject(transaction.error??new Error('Event storage transaction aborted'));
      action(transaction.objectStore('events'),result=>{value=result;});
    });
  }

  async pending() {
    return this.transaction<BrowserEvent[]>('readonly',(store,result)=>{
      const request=store.index('state').getAll([this.session,'pending']);
      request.onsuccess=()=>result((request.result as Record[]).map(row=>row.event));
    });
  }

  async hasRejected() {
    return this.transaction<boolean>('readonly',(store,result)=>{
      const request=store.index('state').count([this.session,'rejected']);
      request.onsuccess=()=>result(request.result>0);
    });
  }

  async put(events:BrowserEvent[]) {
    return this.transaction<void>('readwrite',store=>{
      for (const event of events) {
        const request=store.index('identity').getKey([this.session,event.event_id]);
        request.onsuccess=()=>{
          if(request.result===undefined)store.add({session:this.session,eventId:event.event_id,event,state:'pending'} satisfies Record);
        };
      }
    });
  }

  async acknowledge(ids:string[]) {
    return this.transaction<void>('readwrite',store=>{
      for(const id of ids) {
        const request=store.index('identity').getKey([this.session,id]);
        request.onsuccess=()=>{if(request.result!==undefined)store.delete(request.result);};
      }
    });
  }

  async reject(event:BrowserEvent,reason:string) {
    return this.transaction<void>('readwrite',store=>{
      const request=store.index('identity').get([this.session,event.event_id]);
      request.onsuccess=()=>store.put({...request.result,session:this.session,eventId:event.event_id,event,state:'rejected',reason} satisfies Record);
    });
  }
}
