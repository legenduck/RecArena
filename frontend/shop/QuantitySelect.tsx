import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {KeyboardEvent} from 'react';

export function QuantitySelect({value,max,valid,disabled,onChange}:{
  value:string;max:number;valid:boolean;disabled:boolean;onChange:(value:string)=>void;
}) {
  const [open,setOpen]=useState(false);
  const [active,setActive]=useState(1);
  const [position,setPosition]=useState({left:0,top:0,width:0,height:120});
  const anchor=useRef<HTMLSpanElement>(null),select=useRef<HTMLSelectElement>(null);
  const portal=useRef<HTMLDivElement>(null),list=useRef<HTMLUListElement>(null);
  const restorePending=useRef(false);
  function show(){if(disabled)return;setActive(Math.max(1,Math.min(max,Number(value)||1)));setOpen(true);}
  function choose(number:number){setOpen(false);if(String(number)!==value)onChange(String(number));}
  useEffect(()=>{if(disabled)setOpen(false);else if(restorePending.current&&!open){restorePending.current=false;select.current?.focus({preventScroll:true});}},[disabled,open]);
  useEffect(()=>{
    if(!open)return;
    const background=Array.from(document.body.children).filter((e):e is HTMLElement=>e instanceof HTMLElement&&e!==portal.current)
      .map(element=>({element,inert:element.inert,hidden:element.getAttribute('aria-hidden')}));
    function place(){
      const r=anchor.current!.getBoundingClientRect();
      const rowHeight=list.current?.querySelector('li')?.getBoundingClientRect().height||24;
      const available=Math.max(rowHeight,Math.min(135,innerHeight-32));
      const height=Math.floor(available/rowHeight)*rowHeight;
      setPosition({left:Math.max(8,Math.min(r.left,innerWidth-r.width-8)),top:Math.max(8,Math.min(r.top-1,innerHeight-height-22)),width:r.width,height});
    }
    place();list.current?.focus({preventScroll:true});
    background.forEach(({element})=>{element.inert=true;element.setAttribute('aria-hidden','true');});
    const keepFocus=(event:FocusEvent)=>{if(!portal.current?.contains(event.target as Node))list.current?.focus({preventScroll:true});};
    window.addEventListener('resize',place);window.addEventListener('scroll',place,true);document.addEventListener('focusin',keepFocus);
    return ()=>{
      window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);document.removeEventListener('focusin',keepFocus);
      background.forEach(({element,inert,hidden})=>{element.inert=inert;if(hidden===null)element.removeAttribute('aria-hidden');else element.setAttribute('aria-hidden',hidden);});
      if(select.current?.isConnected){if(select.current.disabled)restorePending.current=true;else select.current.focus({preventScroll:true});}
    };
  },[open]);
  useEffect(()=>{if(open)document.getElementById(`quantity-option-${active}`)?.scrollIntoView({block:'nearest'});},[active,open]);
  function key(event:KeyboardEvent) {
    if(event.key==='Escape'||event.key==='Tab'){event.preventDefault();setOpen(false);}
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(active);}
    else if(['ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key)){
      event.preventDefault();setActive(n=>event.key==='Home'?1:event.key==='End'?max:Math.max(1,Math.min(max,n+({ArrowUp:-1,ArrowDown:1,PageUp:-5,PageDown:5}[event.key]??0))));
    }
  }
  return <span ref={anchor} className="a-dropdown-container quantity-control">
    <label htmlFor="quantity" className="a-offscreen">Quantity:</label>
    <select ref={select} id="quantity" name="quantity" className="a-native-dropdown a-declarative" role="combobox"
      value={value} disabled={disabled} aria-invalid={!valid} aria-expanded={open} aria-controls={open?'quantity-options':undefined}
      onChange={e=>onChange(e.target.value)} onMouseDown={e=>{if(e.button===0){e.preventDefault();show();}}}
      onKeyDown={e=>{if(['ArrowDown','ArrowUp','Enter',' '].includes(e.key)){e.preventDefault();show();}}}>
      {!valid&&<option value={value} disabled>{value}</option>}
      {Array.from({length:max},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}
    </select>
    <span className="a-button a-button-dropdown" tabIndex={-1} aria-hidden="true"><span className="a-button-inner">
      <span className="a-button-text quantity-caption"><span className="a-dropdown-label">Quantity: </span><span className="a-dropdown-prompt">{value}</span></span>
      <i className="a-icon a-icon-dropdown"/>
    </span></span>
    {open&&createPortal(<div ref={portal} className="quantity-overlay" onPointerDown={e=>{if(e.target===e.currentTarget)setOpen(false);}}>
      <div className="a-popover quantity-popover" role="dialog" aria-modal="true" style={{left:position.left,top:position.top,width:position.width}}>
        <div className="a-popover-inner a-lgtbox-vertical-scroll" style={{maxHeight:position.height}}>
          <ul id="quantity-options" ref={list} role="listbox" tabIndex={-1} aria-activedescendant={`quantity-option-${active}`}
            className="a-nostyle a-list-link" onKeyDown={key}>{Array.from({length:max},(_,i)=>i+1).map(n=><li key={n} className="a-dropdown-item" role="presentation">
            <a id={`quantity-option-${n}`} role="option" aria-selected={String(n)===value} className={`a-dropdown-link${active===n?' a-active':''}`}
              onPointerMove={()=>setActive(n)} onClick={()=>choose(n)}>{n}</a>
          </li>)}</ul>
        </div>
      </div>
    </div>,document.body)}
  </span>;
}
