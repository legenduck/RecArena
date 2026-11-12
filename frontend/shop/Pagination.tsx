import React from 'react';
import {text} from './strings';
import {activateOnSpace} from './controls';

export function Pagination({page,pages,disabled,hrefFor,onChange,adjacentOnly=false}:{page:number;pages:number;disabled:boolean;hrefFor:(page:number)=>string;onChange:(page:number)=>void;adjacentOnly?:boolean}) {
  const count=Math.max(1,pages);
  const start=Math.max(1,Math.min(page-2,count-4));
  const numbers=adjacentOnly?[page]:[...new Set([1,...Array.from({length:Math.min(5,count)},(_,i)=>start+i),count])].sort((a,b)=>a-b);
  const link=(number:number,kind:'previous'|'next'|'button',current=false,unavailable=false)=>{
    const arrow=<svg className={`s-pagination-${kind==='previous'?'left':'right'}-arrow`} width="8" height="12" viewBox="0 0 8 12" aria-hidden="true"><path d={kind==='previous'?'M7 1 2 6l5 5':'m1 1 5 5-5 5'} fill="none" stroke="currentColor" strokeWidth="2"/></svg>;
    const content=kind==='previous'?<>{arrow}{text.previous}</>:kind==='next'?<>{text.next}{arrow}</>:number;
    const label=kind==='button'?`Go to page ${number}`:`Go to ${kind} page, page ${number}`;
    return current||disabled||unavailable
      ? <span className={`s-pagination-item ${current?'s-pagination-selected':`s-pagination-${kind} s-pagination-disabled`}`} role="button" tabIndex={0}
          aria-current={current?'page':undefined} aria-disabled={!current?true:undefined} aria-label={current?`Page ${number}`:kind==='button'?label:undefined}
          onKeyDown={e=>{if(e.key===' '||e.key==='Enter')e.preventDefault();}}>{content}</span>
      : <a className={`s-pagination-item s-pagination-${kind} s-pagination-button-accessibility`} role="button" tabIndex={0} href={hrefFor(number)} aria-label={label} onKeyDown={activateOnSpace}
          onClick={e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();onChange(number);}}>{content}</a>;
  };
  return <div role="navigation" aria-label="pagination" className="pagination"><span className="s-pagination-strip"><ul className="a-unordered-list a-horizontal s-unordered-list-accessibility">
    <li className="s-list-item-margin-right-adjustment"><span className="a-list-item">{link(Math.max(1,page-1),'previous',false,page<=1)}</span></li>
    {numbers.map((number,index)=><React.Fragment key={number}>
      {index>0&&number-numbers[index-1]>1&&<li className="s-list-item-margin-right-adjustment" aria-hidden="true"><span className="a-list-item"><span className="s-pagination-item s-pagination-ellipsis">…</span></span></li>}
      <li className="s-list-item-margin-right-adjustment"><span className="a-list-item">{link(number,'button',number===page)}</span></li>
    </React.Fragment>)}
    <li className="s-list-item-margin-right-adjustment"><span className="a-list-item">{link(Math.min(count,page+1),'next',false,page>=count)}</span></li>
  </ul></span></div>;
}
