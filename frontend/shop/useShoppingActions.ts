import {useRef,useState} from 'react';
import type {BrowserSession as ShopSessionResponse,BrowserReceipt as PurchaseResponse,BrowserCart} from '../generated/api';
import {api} from '../shared/api';
import {uuid} from '../shared/uuid';
import type {ShoppingPage} from './page';

// Retry keys survive response loss, while distinct actions get distinct keys.
export function useShoppingActions(page:ShoppingPage,base:string) {
  const [session,setSession]=useState(page.session);
  const [cart,setCart]=useState(page.cart);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(page.error??'');
  const [notice,setNotice]=useState('');
  const purchaseRetry=useRef({payload:'',key:''});
  const cartRetry=useRef({payload:'',key:''});
  const cartPending=useRef(false);
  const request=<T,>(path:string,options:RequestInit={})=>api<T>(path,options,base);
  async function refreshSession() {
    const value=await request<ShopSessionResponse>('/session');
    setSession(value);return value;
  }
  async function buy(productId:string,variantId:string,quantity:number,itemKey:string|null,purchaseView:string) {
    const payload=JSON.stringify({viewId:purchaseView,product_id:productId,variant_id:variantId,quantity,item_key:itemKey});
    if(purchaseRetry.current.payload!==payload)purchaseRetry.current={payload,key:uuid()};
    setBusy(true);setError('');
    try {
      await request<PurchaseResponse>('/purchases',{method:'POST',headers:{'Idempotency-Key':purchaseRetry.current.key},body:payload});
      purchaseRetry.current={payload:'',key:''};setNotice('Your simulated purchase has been recorded.');
      await refreshSession();
    } catch(e) {setError((e as Error).message);await refreshSession().catch(()=>{});}
    finally {setBusy(false);}
  }
  async function mutateCart(path:string,body:unknown,method='POST') {
    if(cartPending.current)return;
    cartPending.current=true;
    const payload=JSON.stringify(body), identity=method+path+payload;
    if(cartRetry.current.payload!==identity)cartRetry.current={payload:identity,key:uuid()};
    setBusy(true);setError('');
    try {
      const value=await request<BrowserCart>(path,{method,headers:{'Idempotency-Key':cartRetry.current.key},body:payload});
      cartRetry.current={payload:'',key:''};
      if(cart)setCart(value);
      setSession(s=>s?{...s,cart_quantity:value.total_quantity}:s);
      setNotice(path==='/cart/items'?'Added to cart.':method==='DELETE'?'':'Cart updated.');
      return value;
    } catch(e) {
      setError((e as Error).message);
      if(cart)await request<BrowserCart>(`/cart?viewId=${cart.viewId}`).then(setCart).catch(()=>{});
      await refreshSession().catch(()=>{});
    } finally {cartPending.current=false;setBusy(false);}
  }
  async function addToCart(productId:string,variantId:string,quantity:number,itemKey:string|null,view:string) {
    await mutateCart('/cart/items',{viewId:view,product_id:productId,variant_id:variantId,quantity,item_key:itemKey});
  }
  async function checkout() {
    if(!cart||cartPending.current)return;
    const payload=JSON.stringify({viewId:cart.viewId});
    if(purchaseRetry.current.payload!==payload)purchaseRetry.current={payload,key:uuid()};
    setBusy(true);setError('');
    try {
      await request<PurchaseResponse>('/cart/checkout',{method:'POST',headers:{'Idempotency-Key':purchaseRetry.current.key},body:payload});
      purchaseRetry.current={payload:'',key:''};
      await refreshSession();
    } catch(e) {
      setError((e as Error).message);
      await request<BrowserCart>(`/cart?viewId=${cart.viewId}`).then(setCart).catch(()=>{});
      await refreshSession().catch(()=>{});
    } finally {setBusy(false);}
  }
  async function abandon(viewId:string) {
    setBusy(true);setError('');
    try {await request('/abandon',{method:'POST',body:JSON.stringify({viewId})});await refreshSession();}
    catch(e){setError((e as Error).message);}
    finally{setBusy(false);}
  }
  return {session,cart,busy,setBusy,error,setError,notice,buy,mutateCart,addToCart,checkout,abandon};
}
