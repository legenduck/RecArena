import {uuid} from '../shared/uuid';
import type {BrowserEvent as ClientEvent} from '../generated/api';
import {TelemetryStore} from './telemetryStore';

export type PageMeasurement = {viewId:string;viewed:boolean;reviews:Set<string>};
export const newPageMeasurement = (viewId:string):PageMeasurement => ({viewId,viewed:false,reviews:new Set()});
export type ListPresentation = {id:string;eventId:string;reported:boolean};
export const newListPresentation=():ListPresentation=>({id:uuid(),eventId:uuid(),reported:false});

let documentIdentity:{document:Document;id:string;sequence:number}|undefined;
function currentDocument() {
  if(!documentIdentity||documentIdentity.document!==window.document)
    documentIdentity={document:window.document,id:uuid(),sequence:0};
  return documentIdentity;
}

export class Telemetry {
  private store:TelemetryStore;
  constructor(private sessionPrefix:string) {this.store=new TelemetryStore(sessionPrefix);}
  private queue:ClientEvent[]=[];
  private rejected:ClientEvent[]=[];
  private unpersisted=new Set<string>();
  private writes:Promise<void>=Promise.resolve();
  private ready:Promise<void>|undefined;
  private inflight=false;
  private timer:ReturnType<typeof setInterval>|undefined;
  private rejectedRecords=false;
  private stopped=false;
  private single=false;
  private retryAt=0;
  private retryDelay=1000;
  private storageFailed=false;
  start() {
    this.stopped=false;
    if (this.timer) return;
    this.ready??=this.restore();
    this.timer=setInterval(()=>void this.flush(),1000);
    window.addEventListener('pagehide',this.onExit);
  }
  emit(page:PageMeasurement,type:ClientEvent['event_type'],payload:ClientEvent['payload'],eventId=uuid(),viewId=page.viewId) {
    if (!viewId) return;
    const document=currentDocument();
    const event:ClientEvent={viewId,documentId:document.id,event_id:eventId,event_type:type,occurred_at:new Date().toISOString(),
      client_sequence:++document.sequence,payload:structuredClone(payload)};
    this.queue.push(event);this.unpersisted.add(eventId);
    this.persist(async()=>{await this.store.put([event]);this.unpersisted.delete(eventId);});
    if (this.queue.length>=20||this.stopped) void this.flush(this.stopped);
  }
  private onExit=()=>{void this.flush(true);};
  private async restore() {
    try {
      const [saved,rejected]=await Promise.all([this.store.pending(),this.store.hasRejected()]);
      const queued=new Set(this.queue.map(event=>event.event_id));
      this.queue=[...saved.filter(event=>!queued.has(event.event_id)),...this.queue];
      if(rejected){this.rejectedRecords=true;this.reportFailure('PREVIOUSLY_REJECTED',0,false);}
    } catch {this.storageFailure();}
  }
  private persist(action:()=>Promise<void>) {
    this.writes=this.writes.then(action).catch(()=>this.storageFailure());
    return this.writes;
  }
  private storageFailure() {
    if(!this.storageFailed) {
      this.storageFailed=true;
      console.warn('Shopping activity storage unavailable; delivery continues');
      window.dispatchEvent(new CustomEvent('recarena-telemetry-status',{detail:'Activity logging storage is unavailable.'}));
    }
  }
  private retry(code:string,events:ClientEvent[]) {
    this.queue.unshift(...events);
    this.retryAt=performance.now()+this.retryDelay;
    this.retryDelay=Math.min(this.retryDelay*2,30000);
    this.reportFailure(code,events.length,true);
  }
  async flush(keepalive=false) {
    if(this.inflight||(!keepalive&&performance.now()<this.retryAt))return;
    this.inflight=true;
    let events:ClientEvent[]=[];
    try {
      await this.ready;await this.writes;
      if(!this.queue.length)return;
      const viewId=this.queue[0].viewId;
      let count=0;
      while(count<(this.single?1:20)&&this.queue[count]?.viewId===viewId)count++;
      events=this.queue.splice(0,count);
      const unsaved=events.filter(event=>this.unpersisted.has(event.event_id));
      if(unsaved.length)await this.persist(async()=>{
        await this.store.put(unsaved);unsaved.forEach(event=>this.unpersisted.delete(event.event_id));
      });
      const response=await fetch(this.sessionPrefix+'/api/shop/v1/events/batch',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({events}),keepalive});
      if (!response.ok) {
        const retrying=response.status>=500 || response.status===429;
        if(retrying)this.retry(`HTTP_${response.status}`,events);
        else if(events.length>1) {
          this.single=true;this.queue.unshift(...events);
        } else {
          this.rejected.push(events[0]);
          await this.persist(()=>this.store.reject(events[0],`HTTP_${response.status}`));
          this.unpersisted.delete(events[0].event_id);
          this.reportFailure(`HTTP_${response.status}`,1,false);
        }
      } else {
        const receipt=await response.json();
        if(!Array.isArray(receipt.accepted_event_ids)||!Array.isArray(receipt.duplicate_event_ids))throw new Error('Invalid acknowledgement');
        const ids=new Set<string>([...receipt.accepted_event_ids,...receipt.duplicate_event_ids]);
        const expected=new Set(events.map(event=>event.event_id));
        if([...ids].some(id=>typeof id!=='string'||!expected.has(id)))throw new Error('Unexpected acknowledgement');
        await this.persist(()=>this.store.acknowledge([...ids]));
        const remaining=events.filter(event=>!ids.has(event.event_id));
        if(remaining.length)this.retry('INCOMPLETE_ACKNOWLEDGEMENT',remaining);
        else {this.retryAt=0;this.retryDelay=1000;}
        if(!this.queue.length&&!this.rejectedRecords&&!this.storageFailed)
          window.dispatchEvent(new CustomEvent('recarena-telemetry-status',{detail:null}));
      }
    } catch {if(events.length)this.retry('DELIVERY_ERROR',events);}
    finally {
      this.inflight=false;
      if(this.stopped&&!this.queue.length)this.store.close();
    }
    if(!this.queue.length)this.single=false;
    if(this.queue.length&&(this.single||this.queue.length>=20||this.stopped))
      setTimeout(()=>void this.flush(this.stopped),Math.max(0,this.retryAt-performance.now()));
  }
  stop() {this.stopped=true;clearInterval(this.timer);this.timer=undefined;window.removeEventListener('pagehide',this.onExit);void this.flush(true);}
  private reportFailure(code:string,count:number,retrying:boolean) {
    if (!retrying) this.rejectedRecords=true;
    console.warn('Shopping activity delivery failed',{code,count,retrying});
    window.dispatchEvent(new CustomEvent('recarena-telemetry-status',{detail:retrying?'Activity logging is retrying.':'Some activity records were rejected.'}));
  }
}

export function presentList(page:PageMeasurement,telemetry:Telemetry,presentation:ListPresentation,payload:ClientEvent['payload'],viewId=page.viewId) {
  if (presentation.reported || !viewId) return;
  presentation.reported=true;
  telemetry.emit(page,'item_list_rendered',{...payload,list_presentation_id:presentation.id},presentation.eventId,viewId);
}

export function observeScroll(page:PageMeasurement,telemetry:Telemetry) {
  let last=0;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let position={scroll_x:window.scrollX,scroll_y:window.scrollY,viewport_width:window.innerWidth,viewport_height:window.innerHeight};
  function emit() {last=performance.now();timer=undefined;telemetry.emit(page,'scroll_sampled',position);}
  function changed() {
    position={scroll_x:Math.max(0,window.scrollX),scroll_y:Math.max(0,window.scrollY),viewport_width:window.innerWidth,viewport_height:window.innerHeight};
    if (performance.now()-last>=250) emit();
    else if (!timer) timer=setTimeout(emit,250-(performance.now()-last));
  }
  emit();
  window.addEventListener('scroll',changed,{passive:true});
  // Let an already scheduled final sample keep its 250ms boundary and captured
  // old-page position, rather than emitting another sample immediately on exit.
  return ()=>{window.removeEventListener('scroll',changed);};
}
