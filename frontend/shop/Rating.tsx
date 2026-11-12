import React from 'react';
import {activateOnSpace} from './controls';

export function Stars({value,label,hidden=false,hook,size='standard'}: {value:number;label?:string;hidden?:boolean;hook?:string;size?:'standard'|'mini'|'medium'}) {
  const stars = Math.round(Math.max(0, Math.min(5, value)) * 2) / 2;
  const description = label ?? `${Number(value.toFixed(1))} out of 5 stars`;
  const kind=size==='standard'?'star':`star-${size}`;
  return <i className={`a-icon a-icon-${kind} a-${kind}-${String(stars).replace('.','-')} rating-stars`} aria-hidden={hidden||undefined} data-hook={hook} title={description}>
    <span className="a-icon-alt">{description}</span>
  </i>;
}

export const compactReviewCount=(count:number)=>new Intl.NumberFormat('en-US',{
  notation:count>=1000?'compact':'standard',maximumFractionDigits:1,
}).format(count);

export function Rating({value,href,onClick,onAuxClick}: {
  value:number|null;href?:string;onClick?:React.MouseEventHandler<HTMLAnchorElement>;onAuxClick?:React.MouseEventHandler<HTMLAnchorElement>;
}) {
  if (value === null) return <>No ratings</>;
  return <span className="rating-value a-row a-size-small"><span className="a-size-small a-color-base" aria-hidden="true">{value.toFixed(1)}</span>
    {href?<a role="button" href={href} aria-label={`${value.toFixed(1)} out of 5 stars, rating details`}
      onClick={onClick} onAuxClick={onAuxClick} onKeyDown={activateOnSpace}><Stars value={value} hidden size="mini"/></a>:<Stars value={value} size="mini"/>}
  </span>;
}
