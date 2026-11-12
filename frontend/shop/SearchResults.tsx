import React,{useLayoutEffect,useState} from 'react';
import type {BrowserResults as SearchResponse,BrowserBlockResponse as BlockResponse,ResultFilters} from '../generated/api';
import {api} from '../shared/api';
import {uuid} from '../shared/uuid';
import {text} from './strings';
import {newListPresentation,presentList,ListPresentation,PageMeasurement,Telemetry} from './telemetry';
import {SearchSidebar} from './SearchSidebar';
import {Card} from './ProductCard';
import {Pagination} from './Pagination';

type PurchaseAction=(product:string,variant:string,quantity:number,item:string|null,view:string)=>Promise<void>;
export function SearchResults({initialResult,base,busy,setBusy,cartEnabled,navigate,buy,addToCart,telemetry,measurement,onError}:{
  initialResult:SearchResponse; base:string; busy:boolean; setBusy:(busy:boolean)=>void; cartEnabled:boolean;
  navigate:(path:string,shallow?:boolean)=>Promise<void>; buy:PurchaseAction; addToCart:PurchaseAction;
  telemetry:Telemetry; measurement:PageMeasurement; onError:(error:string)=>void;
}) {
  const [result,setResult]=useState(initialResult);
  const [presentations,setPresentations]=useState<Record<string,ListPresentation>>(()=>
    Object.fromEntries(initialResult.blocks.map(block=>[block.block_id,newListPresentation()])));
  const href=(path:string)=>path.startsWith(base+'/')?path:base+path;
  const request=<T,>(path:string)=>api<T>(path,{},base);
  function resultHref(page:number,filters:ResultFilters=result?.applied_filters??{}) {
    const params=new URLSearchParams({q:result!.query,page:String(page)});
    if(Object.values(filters).some(value=>value!=null))params.set('filters',JSON.stringify(filters));
    return href(`/results/${result!.viewId}?${params}`);
  }
  function sectionHref(blockId:string,page:number) {
    const sections=Object.fromEntries(result!.blocks.filter(b=>b.component==='paged_row').map(b=>[b.block_id,b.block_id===blockId?page:b.section_page]));
    return href(`/results/${result!.viewId}?`+new URLSearchParams({q:result!.query,page:String(result!.main_page),section_pages:JSON.stringify(sections),filters:JSON.stringify(result!.applied_filters??{})}));
  }
  async function sectionPage(blockId:string,page:number) {
    if(!result)return;
    setBusy(true);onError('');
    try {
      const value=await request<BlockResponse>(`/results/${result.viewId}/blocks/${encodeURIComponent(blockId)}?main_page=${result.main_page}&section_page=${page}&filters=${encodeURIComponent(JSON.stringify(result.applied_filters??{}))}`);
      setResult({...result,blocks:result.blocks.map(b=>b.block_id===blockId?value.block:b)});
      setPresentations({...presentations,[blockId]:newListPresentation()});
      telemetry.emit(measurement,'section_page_changed',{block_id:blockId},uuid(),value.viewId);
      await navigate(sectionHref(blockId,page),true);
    } catch(e){onError((e as Error).message);}
    finally{setBusy(false);}
  }
  return <><h1 className="s-desktop-toolbar"><span>{result.result_count?`${(result.main_page-1)*result.main_page_size+1}-${Math.min(result.main_page*result.main_page_size,result.result_count)} of ${result.result_count} results`:'0 results'} for</span>{' '}
          <span className="a-color-state">"{result.query}"</span></h1>
        <div className={result.filter_options?'search-layout search-layout-with-sidebar':'search-layout'}>
          <div className="search-results">
            {result.result_count===0&&<p>{text.noResults}</p>}
            {result.blocks.map(block=><div key={block.block_id} className="search-results-block">
              <RenderedList result={result} blockId={block.block_id} presentation={presentations[block.block_id]} measurement={measurement} telemetry={telemetry}/>
              <div className="results-block-heading"><h2>{block.title==='Search results'?'Results':block.title}</h2></div>
              <div role="list" className="s-main-slot s-result-list s-search-results sg-row product-grid" style={{'--columns':block.columns} as React.CSSProperties}>
                {block.items.map((card,index)=><Card key={card.item_key} card={card} position={index+1} base={base} disabled={busy} navigate={path=>void navigate(path)}
                  cartEnabled={cartEnabled} buy={(p,v,q,o)=>cartEnabled?addToCart(p,v,q,o,block.viewId):buy(p,v,q,o,block.viewId)} telemetry={telemetry} measurement={measurement}
                  presentation={presentations[block.block_id]} viewId={block.viewId} blockId={block.block_id}/>)}
              </div>
              {block.component==='paged_row'&&<Pagination page={block.section_page} pages={block.section_page+(block.has_next_page?1:0)}
                adjacentOnly disabled={busy} hrefFor={page=>sectionHref(block.block_id,page)} onChange={page=>void sectionPage(block.block_id,page)}/>}
            </div>)}
            {result.result_count>0&&<Pagination page={result.main_page} pages={Math.ceil(result.result_count/result.main_page_size)}
              disabled={busy} hrefFor={resultHref} onChange={page=>void navigate(resultHref(page))}/>}
          </div>
          {result.filter_options&&<SearchSidebar options={result.filter_options} filters={result.applied_filters??{}} disabled={busy}
            hrefFor={filters=>resultHref(1,filters)} onChange={filters=>void navigate(resultHref(1,filters))}/>}
        </div></>;
}

function RenderedList({result,blockId,presentation,measurement,telemetry}:{result:SearchResponse;blockId:string;presentation:ListPresentation;measurement:PageMeasurement;telemetry:Telemetry}) {
  const block=result.blocks.find(b=>b.block_id===blockId)!;
  useLayoutEffect(()=>{
    presentList(measurement,telemetry,presentation,{block_id:blockId,item_keys:block.items.map(i=>i.item_key)},block.viewId);
  },[result,block,presentation,measurement,telemetry,blockId]);
  return null;
}
