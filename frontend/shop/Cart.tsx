import {useState} from 'react';
import type {BrowserCart} from '../generated/api';
import {Price} from './Price';
import {SubmitButton} from './controls';
import {Availability} from './Availability';

export function CartTotals({values}:{values:Record<string,number|null>}) {
  return <>{Object.entries(values).map(([currency,amount])=><span className="cart-currency-total" key={currency}>
    {amount===null?'Price not provided':<Price amount={amount} currency={currency}/>}
  </span>)}</>;
}

type CartResult=Promise<BrowserCart|undefined>;
export function Cart({cart,base,maxQuantity,busy,update,remove,checkout}:{
  cart:BrowserCart;base:string;maxQuantity:number;busy:boolean;
  update:(id:string,quantity:number)=>CartResult;remove:(id:string)=>CartResult;checkout:()=>void;
}) {
  const [pending,setPending]=useState<string|null>(null);
  const [removed,setRemoved]=useState<{title:string;href:string}|null>(null);
  async function change(id:string,quantity:number) {
    setPending(id);try{await update(id,quantity);}finally{setPending(null);}
  }
  async function erase(item:BrowserCart['items'][number],href:string) {
    setPending(item.item_id);
    try{const result=await remove(item.item_id);if(result)setRemoved({title:item.title,href});}
    finally{setPending(null);}
  }
  return <div className={`cart-layout${cart.items.length?'':' cart-layout-empty'}`}>
    {cart.items.length>0&&<div id="sc-buy-box" className="cart-summary">
      <h3 className="cart-subtotal" aria-live="polite">Subtotal ({cart.total_quantity} {cart.total_quantity===1?'item':'items'}):{' '}
        <span id="sc-subtotal-amount-buybox" className="cart-total"><CartTotals values={cart.totals_by_currency}/></span>
      </h3>
      <form method="post" action={`${base}/api/shop/v1/cart/checkout`} onSubmit={event=>{event.preventDefault();if(!busy&&cart.items.length)checkout();}}>
        <SubmitButton name="submit.buy-now" label="Buy Now" disabled={busy||cart.items.length===0}/>
      </form>
    </div>}
    <div id="sc-active-cart" className="cart-panel"><h2 id="sc-active-items-header">{cart.items.length?'Shopping Cart':'Your RecArena Cart is empty'}</h2>
      {removed&&<div className="sc-list-item-removed-msg" role="status"><a href={removed.href} target="_blank" rel="noopener">{removed.title}</a> was removed from Shopping Cart.</div>}
      {cart.items.length===0?<div className="cart-empty"><a href={base+'/'}>Continue shopping</a></div>:<>
      <div className="sc-cart-header"><span className="a-color-secondary">Price</span></div>
      <ul className="cart-items a-unordered-list a-nostyle a-vertical" data-name="Active Items" aria-labelledby="sc-active-items-header">{cart.items.map(item=>{
        const href=`${base}/products/${encodeURIComponent(item.product_id)}?view=${cart.viewId}&item=${item.item_id}`;
        return <div role="listitem" className="sc-list-item cart-item" key={item.item_id} data-asin={item.product_id} data-itemtype="active">
          <div className="sc-list-item-content">
            <a className="sc-product-link cart-image-link" href={href} target="_blank" rel="noopener" aria-hidden="true" tabIndex={-1}><img className="sc-product-image" src={item.image_url} alt={item.title}/></a>
            <div className="cart-item-info">
              <a className="sc-product-link sc-product-title" href={href} target="_blank" rel="noopener"><h3>
                <span className="a-truncate"><span className="a-truncate-full a-offscreen">{item.title}</span><span className="a-truncate-cut" aria-hidden="true">{item.title}</span></span>
              </h3></a>
              <div className="sc-product-price cart-item-price"><Price amount={item.unit_price_minor} currency={item.currency}/></div>
              <div className="cart-item-description">
                <div className="sc-product-availability"><Availability available={item.is_available} purchasable={item.is_purchasable}/></div>
                {Object.keys(item.selected_options).length>0&&<ul className="sc-product-variation">
                  {Object.entries(item.selected_options).map(([key,value])=><li key={key}><span className="a-text-bold">{key}: </span><span>{value}</span></li>)}
                </ul>}
                <div className="cart-item-actions"><CartQuantity quantity={item.quantity} max={maxQuantity} busy={busy} pending={pending===item.item_id} title={item.title}
                  onChange={quantity=>void change(item.item_id,quantity)} onDelete={()=>void erase(item,href)}/>
                  <form method="post" action={`${base}/api/shop/v1/cart/items/${item.item_id}`} onSubmit={event=>{event.preventDefault();if(!busy)void erase(item,href);}}>
                    <input type="submit" className="cart-remove" value="Delete" aria-label={`Delete ${item.title}`} disabled={busy}/>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </div>;
      })}</ul></>}
    </div>
  </div>;
}

function CartQuantity({quantity,max,busy,pending,title,onChange,onDelete}:{quantity:number;max:number;busy:boolean;pending:boolean;title:string;onChange:(n:number)=>void;onDelete:()=>void}) {
  return <fieldset name="sc-quantity" className="a-stepper-expanding-fieldset cart-quantity">
    <legend className="a-offscreen" aria-hidden="true">Quantity is {quantity}</legend>
    <div className="a-stepper-inner-container"><div className="a-stepper-controls">
      <button type="button" aria-label={quantity===1?`Delete ${title}`:`Decrease quantity by one, Quantity is ${quantity}, ${title}`} disabled={busy}
        onClick={()=>quantity===1?onDelete():onChange(quantity-1)}>
        {quantity===1?<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M4 5h12M8 3h4M6 5l1 12h6l1-12M9 8v6m2-6v6" fill="none" stroke="currentColor" strokeWidth="1.5"/></svg>:<span aria-hidden="true">−</span>}
      </button>
      <div className="a-stepper-count-container" aria-busy={pending}>{pending?<><span className="cart-quantity-spinner" aria-hidden="true"/><span className="a-offscreen">Updating quantity</span></>:<span>{quantity}</span>}</div>
      <div className="a-offscreen a-stepper-live-region" aria-live="polite"><span>{quantity}</span></div>
      <button type="button" aria-label={`Increase quantity by one, Quantity is ${quantity}, ${title}`} disabled={busy||quantity>=max} onClick={()=>onChange(quantity+1)}><span aria-hidden="true">+</span></button>
    </div></div>
  </fieldset>;
}
