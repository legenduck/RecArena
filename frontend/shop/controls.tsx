import type {KeyboardEvent} from 'react';

// Anchors with a button role retain native Enter activation and also accept Space.
export function activateOnSpace(event:KeyboardEvent<HTMLElement>) {
  if(event.key===' ') {
    event.preventDefault();
    if(!event.repeat&&event.currentTarget.getAttribute('aria-disabled')!=='true')event.currentTarget.click();
  }
}

export function moveRadio(event:KeyboardEvent<HTMLElement>) {
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
  const group=event.currentTarget.closest('[role="radiogroup"]');
  const choices=Array.from(group?.querySelectorAll<HTMLElement>('[role="radio"]:not(:disabled)')??[]);
  if(!choices.length)return;
  event.preventDefault();
  const current=choices.indexOf(event.currentTarget);
  const next=event.key==='Home'?0:event.key==='End'?choices.length-1:
    (current+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+choices.length)%choices.length;
  choices[next].focus();choices[next].click();
}

export function SubmitButton({label,name,id,title,announceId,disabled,formAction}:{
  label:string;name:string;id?:string;title?:string;announceId?:string;disabled:boolean;formAction?:string;
}) {
  return <span className="a-button a-button-primary purchase-button"><span className="a-button-inner">
    <input className="a-button-input" type="submit" name={name} id={id} title={title} value={label}
      aria-label={announceId?undefined:label} aria-labelledby={announceId} disabled={disabled} formAction={formAction}/>
    <span className="a-button-text" id={announceId} aria-hidden="true">{label}</span>
  </span></span>;
}
