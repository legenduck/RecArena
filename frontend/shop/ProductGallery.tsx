import {useEffect,useRef,useState} from 'react';
import type {KeyboardEvent,MouseEvent} from 'react';
import {createPortal} from 'react-dom';
import {moveRadio} from './controls';
import {expandedImageSource} from './imageSources';

// The viewer's compact title ends at a word/punctuation boundary; the tooltip
// and the product page keep the complete catalog title.
function viewerTitle(title:string) {
  if(title.length<=160)return title;
  const prefix=title.slice(0,157);
  const boundaries=[...prefix.matchAll(/[ .?;,:]/g)];
  return title.slice(0,boundaries.at(-1)?.index??156)+'...';
}

export function ProductGallery({images,title}:{images:readonly string[];title:string}) {
  const [selected,setSelected]=useState(0);
  const [expanded,setExpanded]=useState(false);
  const [zoomed,setZoomed]=useState(false);
  const [natural,setNatural]=useState({width:0,height:0});
  const [size,setSize]=useState({width:0,height:0});
  const [pan,setPan]=useState({x:.5,y:.5});
  const [failed,setFailed]=useState<string|null>(null);
  const backdrop=useRef<HTMLDivElement>(null);
  const dialog=useRef<HTMLDivElement>(null);
  const closeButton=useRef<HTMLButtonElement>(null);
  const opener=useRef<HTMLElement|null>(null);
  const stage=useRef<HTMLDivElement>(null);
  const extra=Math.max(0,images.length-6);
  useEffect(()=>{
    if(!expanded)return;
    const element=dialog.current!;
    const background=Array.from(document.body.children)
      .filter((child):child is HTMLElement=>child instanceof HTMLElement&&child!==backdrop.current)
      .map(element=>({element,inert:element.inert,ariaHidden:element.getAttribute('aria-hidden')}));
    const previousOverflow=document.body.style.overflow;
    closeButton.current?.focus({preventScroll:true});
    background.forEach(({element})=>{element.inert=true;element.setAttribute('aria-hidden','true');});
    document.body.style.overflow='hidden';
    function keydown(event:globalThis.KeyboardEvent) {
      if(event.key==='Escape') {event.preventDefault();event.stopPropagation();setExpanded(false);return;}
      if(event.key!=='Tab')return;
      const choices=Array.from(element.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),[tabindex]:not([tabindex="-1"])')).filter(child=>child.getClientRects().length>0);
      const first=choices[0],last=choices[choices.length-1];
      if(!first) {event.preventDefault();element.focus();return;}
      if(!element.contains(document.activeElement)||document.activeElement===element||event.shiftKey&&document.activeElement===first||!event.shiftKey&&document.activeElement===last) {
        event.preventDefault();(event.shiftKey?last:first).focus();
      }
    }
    function focusin(event:FocusEvent) {
      if(!element.contains(event.target as Node))closeButton.current?.focus({preventScroll:true});
    }
    document.addEventListener('keydown',keydown,true);
    document.addEventListener('focusin',focusin,true);
    return ()=>{
      document.removeEventListener('keydown',keydown,true);
      document.removeEventListener('focusin',focusin,true);
      background.forEach(({element,inert,ariaHidden})=>{
        element.inert=inert;
        if(ariaHidden===null)element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden',ariaHidden);
      });
      document.body.style.overflow=previousOverflow;
      if(opener.current?.isConnected)opener.current.focus({preventScroll:true});
    };
  },[expanded]);
  useEffect(()=>{
    const element=stage.current;if(!expanded||!element)return;
    const measure=()=>setSize({width:element.clientWidth-parseFloat(getComputedStyle(element).paddingRight||'0'),height:element.clientHeight});
    measure();const observer=new ResizeObserver(measure);observer.observe(element);return ()=>observer.disconnect();
  },[expanded]);
  function choose(index:number) { if(index!==selected)setNatural({width:0,height:0});setSelected(index);setZoomed(false);setPan({x:.5,y:.5}); }
  function open(index=selected) {
    opener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
    choose(index);setExpanded(true);
  }
  function close() { setExpanded(false); }
  function activate(event:KeyboardEvent<HTMLElement>) {
    if(event.key==='Enter'||event.key===' ') {event.preventDefault();if(!event.repeat)event.currentTarget.click();}
  }
  function toggleZoom(event:MouseEvent<HTMLDivElement>) {
    const box=stage.current!.getBoundingClientRect();
    setPan(event.detail?{x:Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),y:Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))}:{x:.5,y:.5});
    setZoomed(value=>!value);
  }
  const original=images[selected]??images[0];
  const larger=expandedImageSource(original);
  const expandedSource=failed===larger?original:larger;
  const fit=natural.width&&natural.height&&size.width&&size.height?Math.min(1,size.width/natural.width,size.height/natural.height):1;
  // Some prepared/local images are already smaller than the viewer. Retain
  // magnification for those files; larger originals zoom to their native size.
  const zoomScale=fit<1?1:3;
  const imageWidth=natural.width*(zoomed?zoomScale:fit),imageHeight=natural.height*(zoomed?zoomScale:fit);
  const imageLeft=imageWidth>size.width?(size.width-imageWidth)*pan.x:(size.width-imageWidth)/2;
  const imageTop=imageHeight>size.height?(size.height-imageHeight)*pan.y:(size.height-imageHeight)/2;
  return <div id="leftCol" className="gallery">
    <div id="imageBlock_feature_div"><div id="imageBlock" className="a-section">
    <div className="a-fixed-left-grid"><div className="a-fixed-left-grid-inner">
    <div id="altImages" className="a-fixed-left-grid-col a-col-left">
    <ul className="image-thumbnails a-unordered-list a-nostyle a-button-list a-button-toggle-group a-vertical" role="radiogroup" aria-label="Image thumbnails">
      {images.slice(0,6).map((url,index)=>{
        const overflow=index===5&&extra>0;
        const checked=overflow?selected>=5:selected===index;
        const label=overflow?`View image 6 and ${extra} more ${extra===1?'image':'images'}`:`View image ${index+1}`;
        return <li key={`${index}:${url}`} className={`item imageThumbnail itemNo${index}${overflow?' overlayRestOfImages':''}`}>
          <span className="a-list-item"><span className={`a-button a-button-thumbnail a-button-toggle image-thumbnail${checked?' a-button-selected':''}`}
          onPointerEnter={event=>{if(event.pointerType==='mouse'&&index!==selected)choose(index);}}>
            <span className="a-button-inner">
              <input type="submit" role="radio" className="a-button-input" value=""
                aria-labelledby={`image-thumbnail-${index+1}-announce`} aria-checked={checked}
                aria-posinset={index+1} aria-setsize={Math.min(images.length,6)}
                aria-haspopup={overflow?'dialog':undefined} tabIndex={checked?0:-1}
                onKeyDown={moveRadio} onClick={event=>{event.preventDefault();overflow?open(index):choose(index);}}/>
              <span id={`image-thumbnail-${index+1}-announce`} className="a-button-text" aria-hidden="true">
                <span className="a-offscreen">{label}</span><img src={url} alt="" loading="lazy"/>
                {overflow&&<span className="image-overflow" aria-hidden="true">{extra}+</span>}
              </span>
            </span>
          </span></span>
        </li>;
      })}
    </ul></div>
    <div className="gallery-main a-fixed-left-grid-col a-col-right">
      <div id="main-image-container" className="a-dynamic-image-container">
      <ul className="a-unordered-list a-nostyle a-horizontal main-image-list"><li className="image item itemNo0 selected"><span className="a-list-item">
      <span data-action="main-image-click" className="a-declarative main-image-click">
        <div id="imgTagWrapperId" className="imgTagWrapper image-full-view" role="button" tabIndex={0}
          aria-label={title} aria-haspopup="dialog" onKeyDown={activate} onClick={()=>open()}>
          <img id="landingImage" className="detail-image" src={images[selected]??images[0]} alt={title}/>
        </div>
      </span>
      </span></li></ul>
      </div>
      <span id="canvasCaption"><a href="#" className="full-view-link" aria-haspopup="dialog"
        onClick={event=>{event.preventDefault();open();}}>Click to see full view</a></span>
    </div>
    </div></div></div></div>
    {expanded&&createPortal(<div className="image-viewer-backdrop" ref={backdrop}
      onClick={event=>{if(event.target===event.currentTarget)close();}}>
      <div className="a-popover a-popover-modal image-viewer" ref={dialog} role="dialog" aria-modal="true" aria-label="ImmersiveView" tabIndex={-1}>
      <div className="a-popover-wrapper image-viewer-content">
        <div className="image-viewer-close-row">
          <button type="button" className="a-button-close a-button-top-right image-viewer-close" aria-label="Close" ref={closeButton} onClick={close}><i className="a-icon a-icon-close" aria-hidden="true"/></button>
        </div>
        <div className="a-popover-inner"><div id="iv-tab-view-container">
          <ul className="iv-tab-views image-viewer-header" role="tablist"><li className="iv-tab-heading iv-active" role="tab" id="ivImagesTabHeading"
            aria-selected="true" aria-controls="ivImagesTab"><a href="#ivImagesTab" onClick={event=>event.preventDefault()}>IMAGES</a></li></ul>
        <div id="ivImagesTab" className="iv-box iv-box-tab iv-tab-content" role="tabpanel">
          <div className="iv-box-inner"><div id="ivMain" className="legacyImmersiveView image-viewer-panel">
          <div id="ivStage" className="image-viewer-stage" ref={stage}>
            <span className="a-declarative">
            <div id="ivLargeImage" className="image-viewer-canvas" role="button" tabIndex={0}
              aria-label={zoomed?'Zoom Out Of Image':'Zoom In On Image'} onKeyDown={activate} onClick={toggleZoom}
              onPointerMove={event=>{if(!zoomed)return;const r=event.currentTarget.getBoundingClientRect();setPan({x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))});}}>
              <img src={expandedSource} onLoad={event=>setNatural({width:event.currentTarget.naturalWidth,height:event.currentTarget.naturalHeight})}
                onError={expandedSource!==original?()=>setFailed(larger):undefined}
                style={natural.width?{width:imageWidth,height:imageHeight,left:imageLeft,top:imageTop}: {visibility:'hidden'}}/>
            </div>
            </span>
          </div>
          <div id="ivThumbColumn" className="image-viewer-sidebar">
            <div id="ivTitle" title={title}>{viewerTitle(title)}</div>
            <div id="ivThumbs" className="image-viewer-thumbnails">
              {Array.from({length:Math.ceil(images.length/4)},(_,row)=><div className="ivRow" key={row}>
                {images.slice(row*4,row*4+4).map((url,column)=>{
                  const index=row*4+column;
                  return <div key={`${index}:${url}`} id={`ivImage_${index}`} role="button" className={`ivThumb image-thumbnail${selected===index?' selected':''}`}
                    aria-label={`View image ${index+1}`} aria-pressed={selected===index} tabIndex={0}
                    onKeyDown={activate} onClick={()=>choose(index)}><div className="ivThumbImage"><img src={url} alt="" loading="lazy"/></div></div>;
                })}
              </div>)}
            </div>
          </div>
          </div></div>
        </div>
        </div></div>
      </div>
      </div>
    </div>,document.body)}
  </div>;
}
