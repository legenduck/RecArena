import {useState} from 'react';

export type LoggedEvent={event_id:string;sequence:number;event_type:string;source:string;occurred_at:string;received_at:string;
  recording_method?:string|null;occurrence_relative_to_end?:string;payload:Record<string,unknown>};
export type ResultRecords={purchase:({id:string}&Record<string,unknown>)|null;ranking_results:Array<{result_snapshot_id:string}&Record<string,unknown>>;
  placements?:Array<{placement_id:string}&Record<string,unknown>>;[key:string]:unknown};

export function RunTimeline({events,records}:{events:LoggedEvent[];records:ResultRecords}) {
  const [reference,setReference]=useState<unknown>(null);
  function inspect(kind:string,id:unknown) {
    const value=kind==='purchase_id'?records.purchase:kind==='placement_id'?records.placements?.find(p=>p.placement_id===id):records.ranking_results.find(r=>r.result_snapshot_id===id);
    setReference(value??{reference:id,status:'Reference is retained in the event payload.'});
  }
  const purchasedItems=records.purchase?.items as Array<{title:string;product_id:string;variant_id:string;quantity:number;total_price_minor:number|null;currency:string}>|undefined;
  return <section aria-label="Rollout event timeline">
    {purchasedItems&&<><h3>Confirmed purchase</h3><div className="table-scroll"><table><thead><tr><th>Product</th><th>Variant</th><th>Quantity</th><th>Amount</th></tr></thead>
      <tbody>{purchasedItems.map((item,index)=><tr key={index}><td>{item.title}<br/>{item.product_id}</td><td>{item.variant_id}</td><td>{item.quantity}</td><td>{item.total_price_minor===null?'Price not provided':`${item.currency} ${(item.total_price_minor/100).toFixed(2)}`}</td></tr>)}</tbody></table></div></>}
    <h3>Recorded events</h3>
    <p>Rows follow server receipt sequence. Source occurrence time and server receipt time are shown separately; receipt order does not establish the order of external actions.</p>
    <div className="table-scroll"><table><thead><tr><th>Receipt sequence / event</th><th>Source / recording method</th><th>Occurred</th><th>Received</th><th>References / payload</th></tr></thead><tbody>
      {events.map(e=><tr key={`${e.source}:${e.event_id}`}><td>{e.sequence} · {e.event_type}</td><td>{e.source}<br/>{e.recording_method??'Not recorded'}<br/>{e.occurrence_relative_to_end}</td><td>{e.occurred_at}</td><td>{e.received_at}</td><td>
        {['result_snapshot_id','placement_id','purchase_id'].filter(k=>e.payload[k]).map(k=><button key={k} onClick={()=>inspect(k,e.payload[k])}>{k}: {String(e.payload[k])}</button>)}
        <details><summary>Event data</summary><pre>{JSON.stringify(e,null,2)}</pre></details></td></tr>)}
    </tbody></table></div>{reference!==null && <pre>{JSON.stringify(reference,null,2)}</pre>}
  </section>;
}
