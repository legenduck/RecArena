import React, {useEffect, useRef, useState} from 'react';
import type {PriceBand, PriceFilterOptions, ResultFilters, SearchFilterOptions} from '../generated/api';
import {Stars} from './Rating';

const amount = (minor:number,currency:string) => new Intl.NumberFormat('en-US',{
  style:'currency',currency,minimumFractionDigits:0,maximumFractionDigits:2,
}).format(minor/100);
const THUMB_SIZE=20;
const RANGE_KEYS=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'];
type PriceBound='low'|'high';

export function filterSummary(filters:ResultFilters):string[] {
  const labels:string[]=[];
  if(filters.min_rating!=null)labels.push(`${filters.min_rating} Stars & Up`);
  const {min_price_minor:min,max_price_minor:max,currency}=filters;
  if(currency) {
    if(min!=null&&max!=null)labels.push(`${amount(min,currency)} to ${amount(max,currency)}`);
    else if(min!=null)labels.push(`${amount(min,currency)} & above`);
    else if(max!=null)labels.push(`Up to ${amount(max,currency)}`);
  }
  return labels;
}

function PriceControl({options,filters,disabled,hrefFor,onChange}: {
  options:PriceFilterOptions;filters:ResultFilters;disabled:boolean;hrefFor:(filters:ResultFilters)=>string;onChange:(value:ResultFilters)=>void;
}) {
  const [low,setLow]=useState(filters.min_price_minor??options.min_minor);
  const [high,setHigh]=useState(filters.max_price_minor??options.max_minor);
  const track=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(0);
  const values=useRef({low,high});
  const lastCommit=useRef<string|null>(null);
  const drag=useRef<{pointerId:number;bound:PriceBound;startX:number;start:{low:number;high:number}}|null>(null);
  useEffect(()=>{
    const next={low:filters.min_price_minor??options.min_minor,high:filters.max_price_minor??options.max_minor};
    values.current=next;setLow(next.low);setHigh(next.high);
    drag.current=null;lastCommit.current=null;
  },[filters.min_price_minor,filters.max_price_minor,options.min_minor,options.max_minor]);
  useEffect(()=>{
    const element=track.current;if(!element)return;
    const measure=()=>setWidth(element.getBoundingClientRect().width);
    measure();const observer=new ResizeObserver(measure);observer.observe(element);
    return ()=>observer.disconnect();
  },[]);
  function select(min:number|null,max:number|null) {
    if(disabled)return;
    if(min===(filters.min_price_minor??null)&&max===(filters.max_price_minor??null))return;
    onChange({...filters,min_price_minor:min,max_price_minor:max,currency:min!==null||max!==null?options.currency:null});
  }
  function commit() {
    const current=values.current;
    const min=current.low<=options.min_minor?null:current.low;
    const max=current.high>=options.max_minor?null:current.high;
    const key=JSON.stringify([min,max,options.currency]);
    if(lastCommit.current===key)return;
    lastCommit.current=key;select(min,max);
  }
  function change(bound:PriceBound,value:number) {
    const bounded=Math.max(options.min_minor,Math.min(options.max_minor,Math.round(value)));
    const next={...values.current,[bound]:bound==='low'?Math.min(bounded,values.current.high):Math.max(bounded,values.current.low)};
    values.current=next;setLow(next.low);setHigh(next.high);
  }
  function startDrag(bound:PriceBound,event:React.PointerEvent<HTMLInputElement>) {
    event.preventDefault();if(event.button!==0||drag.current)return;
    const element=event.currentTarget;
    lastCommit.current=null;
    drag.current={pointerId:event.pointerId,bound,startX:event.clientX,start:{...values.current}};
    element.focus({preventScroll:true});element.setPointerCapture(event.pointerId);
  }
  function moveDrag(event:React.PointerEvent<HTMLInputElement>) {
    const current=drag.current;const box=track.current?.getBoundingClientRect();
    if(!current||current.pointerId!==event.pointerId||!box||box.width<=THUMB_SIZE)return;
    const fraction=(event.clientX-current.startX)/(box.width-THUMB_SIZE);
    change(current.bound,current.start[current.bound]+fraction*(options.max_minor-options.min_minor));
  }
  function endDrag(event:React.PointerEvent<HTMLInputElement>) {
    if(drag.current?.pointerId!==event.pointerId)return;
    moveDrag(event);drag.current=null;
    event.currentTarget.releasePointerCapture(event.pointerId);commit();
  }
  function cancelDrag(event:React.PointerEvent<HTMLInputElement>) {
    if(drag.current?.pointerId!==event.pointerId)return;
    const start=drag.current.start;drag.current=null;values.current=start;setLow(start.low);setHigh(start.high);
  }
  function keyStart(event:React.KeyboardEvent<HTMLInputElement>) {
    if(RANGE_KEYS.includes(event.key))lastCommit.current=null;
  }
  function keyCommit(event:React.KeyboardEvent<HTMLInputElement>) {
    if(RANGE_KEYS.includes(event.key))commit();
  }
  const span=options.max_minor-options.min_minor;
  const left=span?Math.max(0,Math.min(100,100*(low-options.min_minor)/span)):0;
  const right=span?Math.max(0,Math.min(100,100*(high-options.min_minor)/span)):100;
  const overlapping=span>0&&(low===high||(width>0&&(right-left)*(width-THUMB_SIZE)/100<THUMB_SIZE));
  const handleLeft=(percent:number)=>`calc(${percent}% - ${THUMB_SIZE*percent/100}px)`;
  function bandLabel(band:PriceBand) {
    if(band.min_minor==null)return `Up to ${amount(band.max_minor!,options.currency)}`;
    if(band.max_minor==null)return `${amount(band.min_minor,options.currency)} & above`;
    return `${amount(band.min_minor,options.currency)} to ${amount(band.max_minor,options.currency)}`;
  }
  const minimum=low<=options.min_minor?null:low;
  const maximum=high>=options.max_minor?null:high;
  const hasPriceFilter=filters.min_price_minor!=null||filters.max_price_minor!=null;
  const cleared={...filters,min_price_minor:null,max_price_minor:null,currency:null};
  const target=new URL(hrefFor({...filters,min_price_minor:minimum,max_price_minor:maximum,currency:minimum!==null||maximum!==null?options.currency:null}),'http://shopping.invalid');
  return <div id="priceRefinements" role="group" aria-label="Price" className="price-filter"><div id="filter-p_36">
    <div className="price-filter-title" id="price-filter-heading"><span>Price</span></div>
    {hasPriceFilter&&<div aria-labelledby="price-filter-heading" className="a-section a-spacing-micro"><a className="filter-clear a-link-normal s-navigation-item s-navigation-clear-link" href={hrefFor(cleared)} aria-disabled={disabled||undefined}
      onClick={event=>{
        if(disabled){event.preventDefault();return;}
        if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
        event.preventDefault();select(null,null);
      }}><span className="s-back-arrow aok-inline-block" aria-hidden="true"/><span>Clear</span></a></div>}
    <div className="price-range-label"><span>{amount(low,options.currency)}</span><span> – </span><span>{amount(high,options.currency)}{options.max_open_ended&&high===options.max_minor?'+':''}</span></div>
    <form method="get" action={target.pathname} onSubmit={event=>{event.preventDefault();commit();}}>
    <div ref={track} className="price-range-slider" data-overlapping={overlapping||undefined}
      style={{'--range-left':`${left}%`,'--range-right':`${right}%`} as React.CSSProperties}>
      <div className="price-range-track"/>
      <input type="range" className="price-range-min" aria-label="Minimum price" aria-valuetext={amount(low,options.currency)}
        style={{left:handleLeft(left)}}
        min={options.min_minor/100} max={options.max_minor/100} step={0.01} value={low/100} disabled={disabled||!span}
        onChange={e=>change('low',Number(e.target.value)*100)} onPointerDown={e=>startDrag('low',e)} onPointerMove={moveDrag}
        onPointerUp={endDrag} onPointerCancel={cancelDrag} onKeyDown={keyStart} onKeyUp={keyCommit} onBlur={()=>{if(!drag.current)commit();}}/>
      <input type="range" className="price-range-max" aria-label="Maximum price" aria-valuetext={amount(high,options.currency)}
        style={{left:handleLeft(right)}}
        min={options.min_minor/100} max={options.max_minor/100} step={0.01} value={high/100} disabled={disabled||!span}
        onChange={e=>change('high',Number(e.target.value)*100)} onPointerDown={e=>startDrag('high',e)} onPointerMove={moveDrag}
        onPointerUp={endDrag} onPointerCancel={cancelDrag} onKeyDown={keyStart} onKeyUp={keyCommit} onBlur={()=>{if(!drag.current)commit();}}/>
    </div>
    {Array.from(target.searchParams).map(([name,value])=><input key={name} type="hidden" name={name} value={value}/>)}
    <input type="hidden" name="low-price" value={minimum===null?'':(minimum/100).toFixed(2)}/>
    <input type="hidden" name="high-price" value={maximum===null?'':(maximum/100).toFixed(2)}/>
    </form>
    {!!options.bands?.length&&<ul className="price-bands">{options.bands.map((band,index)=>{
      const value={...filters,min_price_minor:band.min_minor??null,max_price_minor:band.max_minor??null,currency:options.currency};
      return <li key={index}><span className="a-list-item"><a className="filter-choice" href={hrefFor(value)}
        aria-current={(filters.min_price_minor??null)===(band.min_minor??null)&&(filters.max_price_minor??null)===(band.max_minor??null)?'true':'false'}
        aria-disabled={disabled||undefined} onClick={event=>{
          if(disabled){event.preventDefault();return;}
          if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
          event.preventDefault();select(band.min_minor??null,band.max_minor??null);
        }}>{bandLabel(band)}</a></span></li>;
    })}</ul>}
  </div></div>;
}

export function SearchSidebar({options,filters,disabled,hrefFor,onChange}: {
  options:SearchFilterOptions;filters:ResultFilters;disabled:boolean;hrefFor:(filters:ResultFilters)=>string;onChange:(filters:ResultFilters)=>void;
}) {
  const clearedRating={...filters,min_rating:null};
  function follow(event:React.MouseEvent<HTMLAnchorElement>,value:ResultFilters) {
    if(disabled){event.preventDefault();return;}
    if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    event.preventDefault();onChange(value);
  }
  return <div id="s-refinements" className="search-sidebar" aria-busy={disabled}>
    <div className="refinement-groups">
      <div id="reviewsRefinements" role="group" aria-labelledby="p_72-title">
        <div id="p_72-title" role="heading" aria-level={2}><span>Customer Reviews</span></div>
        {filters.min_rating!=null&&<div aria-labelledby="p_72-title" className="a-section a-spacing-micro"><a className="filter-clear a-link-normal s-navigation-item s-navigation-clear-link" href={hrefFor(clearedRating)}
          aria-disabled={disabled||undefined} onClick={event=>follow(event,clearedRating)}><span className="s-back-arrow aok-inline-block" aria-hidden="true"/><span>Clear</span></a></div>}
        <ul id="filter-p_72" aria-labelledby="p_72-title">{([3,4,5] as const).map(rating=>{
          const selected=filters.min_rating===rating;
          const value={...filters,min_rating:selected?null:rating};
          return <li key={rating}><span className="a-list-item"><a className="a-link-normal s-navigation-item filter-choice rating-filter-choice" href={hrefFor(value)} role="link"
            aria-current={selected?'true':'false'} aria-disabled={disabled||undefined}
            aria-label={selected?`Remove ${rating} Stars & Up filter to expand results`:`Apply ${rating} Stars & Up filter to narrow results`}
            onClick={event=>follow(event,value)}><Stars value={rating} label={`${rating} Stars`} size="medium"/><span>&amp; Up</span></a></span></li>;
        })}</ul>
      </div>
      {options.price&&<PriceControl options={options.price} filters={filters} disabled={disabled} hrefFor={hrefFor} onChange={onChange}/>}
    </div>
  </div>;
}
