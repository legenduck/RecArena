import React,{FormEvent,useEffect,useMemo,useState} from 'react';
import {useRouter} from 'next/router';
import Head from 'next/head';
import {uuid} from '../shared/uuid';
import {money} from '../shared/api';
import {text} from './strings';
import {newPageMeasurement,observeScroll,Telemetry} from './telemetry';
import {filterSummary} from './SearchSidebar';
import {Cart,CartTotals} from './Cart';
import {SearchResults} from './SearchResults';
import {Detail} from './ProductDetail';
import {useShoppingActions} from './useShoppingActions';
import type {ShoppingPage} from './page';

export default function App(page:ShoppingPage&{searchQuery:string;onSearchQueryChange:(query:string)=>void}) {
  const router=useRouter();
  const base=page.sessionId?`/s/${encodeURIComponent(page.sessionId)}`:'';
  const {session,cart,busy,setBusy,error,setError,notice,buy,mutateCart,addToCart,checkout,abandon}=useShoppingActions(page,base);
  const result=page.result,product=page.product;
  const [loggingStatus,setLoggingStatus]=useState<string|null>(null);
  const query=page.searchQuery,setQuery=page.onSearchQueryChange;
  const telemetry=useMemo(()=>new Telemetry(base),[base]);
  const viewId=session?.status==='active'?(result?.viewId??product?.viewId??page.viewId):(session?.viewId??page.viewId);
  const measurement=useMemo(()=>newPageMeasurement(viewId),[viewId]);
  const home=!result&&!product&&!cart;
  const active=session?.status==='active';
  const searchHome=home&&active&&!page.error;
  const pageTitle=!session ? (error==='INVALID_SESSION'?'Session not found':'No session information')
    : !active ? (session.status==='purchased'?text.purchaseTitle:session.status==='abandoned'?'Shopping abandoned':text.ended)
    : page.error ? 'Shopping unavailable'
    : product ? [product.title,product.categories.find(category=>category.trim())].filter(Boolean).join(' : ')
    : result ? [filterSummary(result.applied_filters??{}).length?result.query.replace(/\b\p{L}/gu,letter=>letter.toUpperCase()):result.query,...filterSummary(result.applied_filters??{})].join(' - ')
    : cart ? 'Shopping Cart' : '';
  const href=(path:string)=>path.startsWith(base+'/')?path:base+path;

  async function navigate(path:string,shallow=false) {
    setBusy(true);
    try {await router.push(href(path),undefined,{shallow});}
    catch {setError('PAGE_LOAD_FAILED');}
    finally {setBusy(false);}
  }
  useEffect(()=>{telemetry.start();return ()=>telemetry.stop();},[telemetry]);
  useEffect(()=>{
    const receive=(event:Event)=>setLoggingStatus((event as CustomEvent<string|null>).detail);
    window.addEventListener('recarena-telemetry-status',receive);
    return ()=>window.removeEventListener('recarena-telemetry-status',receive);
  },[]);
  useEffect(()=>{
    if(!session||page.error||measurement.viewed)return;
    measurement.viewed=true;
    telemetry.emit(measurement,'page_viewed',{});
    return observeScroll(measurement,telemetry);
  },[session,active,result,product,measurement,telemetry,page.error]);

  function search(event:FormEvent) {
    event.preventDefault();
    if(!query.trim()||!active||busy)return;
    const params=new URLSearchParams({q:query,request:uuid()});
    void navigate('/search?'+params);
  }
  const searchForm=<form id="nav-search-bar-form" name="site-search" action={href('/search')} method="get" onSubmit={search} className="search-form nav-searchbar nav-progressive-attribute" role="search">
    {home&&<span className="home-search-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5"/></svg></span>}
    <div className="nav-fill"><div className="nav-search-field">
      <label htmlFor="twotabsearchtextbox">{text.searchLabel}</label>
      <input id="twotabsearchtextbox" className="nav-input nav-progressive-attribute" type="text" name="q" role="searchbox" tabIndex={0} aria-label={text.searchLabel} value={query} onChange={e=>setQuery(e.target.value)} placeholder={text.searchLabel} maxLength={512} required autoComplete="off"/>
    </div></div>
    <div className="nav-right"><div className={`nav-search-submit nav-sprite search-submit ${home?'home-search-submit':'header-search-submit'}`}>
      <span id="nav-search-submit-text" className="nav-search-submit-text nav-sprite nav-progressive-attribute" aria-label={text.search}>
        <input id="nav-search-submit-button" className="nav-input nav-progressive-attribute" type="submit" value={text.search} tabIndex={0} disabled={busy||!active}/>
      </span>
    </div></div>
  </form>;
  return <>
    <Head><title>{active&&cart?'RecArena Shopping Cart':pageTitle?`${result&&filterSummary(result.applied_filters??{}).length?'RecArena:':'RecArena :'} ${pageTitle}`:'RecArena'}</title></Head>
    <header>{!searchHome&&<a href={href('/')} className="brand" onClick={e=>{if(!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey){e.preventDefault();void navigate('/');}}}>{text.brand}</a>}
      {!home&&active&&<div className="header-search">{searchForm}</div>}
      <div className="shop-user-status" aria-live="polite">
        <span>{active?'Shopping session active':session?'Shopping session ended':'No session information'}</span>
        {error&&<span role="alert" className="error">{error.replaceAll('_',' ')} ({error})</span>}
        {loggingStatus&&<span role="status">{loggingStatus}</span>}
      </div>
      {active&&session?.show_abandon&&<button type="button" className="quiet" disabled={busy} onClick={()=>void abandon(viewId)}>{text.abandon}</button>}
      {active&&session?.show_cart&&<a id="nav-cart" className="header-cart nav-a" href={href('/cart')} aria-label={`${session.cart_quantity} ${session.cart_quantity===1?'item':'items'} in cart`}
        onClick={e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();void navigate('/cart');}}>
        <span id="nav-cart-count-container" className="cart-icon"><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M2 4h4l3 14h13l3-10H7M10 23h.01M21 23h.01"/></svg><span id="nav-cart-count">{session.cart_quantity}</span></span><span id="nav-cart-text-container">Cart</span>
      </a>}
    </header>
    <main id={product?'dp':undefined} className={result?'results-page':searchHome?'home-page':product?'detail-page':cart?'cart-page':undefined}>
      {notice&&<p className="a-offscreen" role="status">{notice}</p>}
      {!session&&<section className="home"><h1>{error==='INVALID_SESSION'?'Session not found':'No session information'}</h1><p>Open the session URL supplied for this shopping visit.</p></section>}
      {session&&!active&&<section className="confirmation">
        <h1>{session.status==='purchased'?text.purchaseTitle:session.status==='abandoned'?'Shopping abandoned':text.ended}</h1>
        {session.purchase&&<><p>Your purchase has been recorded.</p>
          {session.purchase.items.map((item,index)=><section className="receipt-item" key={index}><h2>{item.title}</h2><dl>
            <dt>Product</dt><dd>{item.product_id}</dd><dt>Options</dt><dd>{Object.entries(item.selected_options).map(([k,v])=>`${k}: ${v}`).join(', ')||'Standard'}</dd>
            <dt>Quantity</dt><dd>{item.quantity}</dd><dt>Unit price</dt><dd>{money(item.unit_price_minor,item.currency)}</dd>
            <dt>Total</dt><dd>{money(item.total_price_minor,item.currency)}</dd></dl></section>)}
          <p>{session.purchase.total_quantity} items · <CartTotals values={session.purchase.totals_by_currency}/></p>
        </>}
      </section>}
      {session&&active&&!page.error&&<>
        {home&&<section className="home home-search"><h1 className="home-wordmark">{text.brand}</h1>{searchForm}</section>}
        {cart&&<Cart cart={cart} base={base} maxQuantity={session.max_quantity} busy={busy}
          update={(id,quantity)=>mutateCart(`/cart/items/${id}`,{viewId:cart.viewId,quantity},'PUT')}
          remove={id=>mutateCart(`/cart/items/${id}`,{viewId:cart.viewId},'DELETE')} checkout={()=>void checkout()}/>}
        {result&&<SearchResults initialResult={result} base={base} busy={busy} setBusy={setBusy} cartEnabled={session.show_cart}
          navigate={navigate} buy={buy} addToCart={addToCart} telemetry={telemetry} measurement={measurement} onError={setError}/>}
        {product&&<Detail key={product.product_id} base={base} product={product} maxQuantity={session.max_quantity} disabled={busy}
          initialReviews={page.reviews!} initialReviewPage={page.reviewPage}
          add={session.show_cart?(p,v,q,o)=>addToCart(p,v,q,o,product.viewId):undefined}
          buy={(p,v,q,o)=>buy(p,v,q,o,product.viewId)} onError={setError} telemetry={telemetry} measurement={measurement}/>}
      </>}
    </main>
  </>;
}
