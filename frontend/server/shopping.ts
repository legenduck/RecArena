import {randomUUID} from 'node:crypto';
import type {GetServerSidePropsContext,GetServerSidePropsResult} from 'next';
import type {ShoppingPage} from '../shop/page';
import type {BrowserProduct as ProductDetail,BrowserReviews as ReviewsResponse,BrowserResults as SearchResponse,BrowserSession as ShopSessionResponse,BrowserCart} from '../generated/api';

const backend=()=> (process.env.RECARENA_PLATFORM_URL ?? 'http://127.0.0.1:8010').replace(/\/$/,'');
const cookieName=()=> process.env.RECARENA_SESSION_COOKIE ?? 'recarena_session';
const noStore='private, no-store, max-age=0, must-revalidate';

class ShoppingError extends Error {
  constructor(public code:string,public status:number){super(code);}
}

async function request<T>(context:GetServerSidePropsContext,sessionId:string|null,path:string,body?:unknown):Promise<T> {
  const headers:Record<string,string>={
    'Content-Type':'application/json',
    'User-Agent':context.req.headers['user-agent'] ?? '',
    'X-RecArena-Response-Kind':context.req.headers['x-nextjs-data'] ? 'data_api':'html',
  };
  // Root recovery checks the actual cookie; prefixed requests never consult it.
  if(!sessionId && context.req.headers.cookie) headers.Cookie=context.req.headers.cookie;
  let response:Response;
  try {
    response=await fetch(backend()+(sessionId?`/s/${encodeURIComponent(sessionId)}`:'')+'/api/shop/v1'+path,
      {method:body===undefined?'GET':'POST',headers,cache:'no-store',
       ...(body===undefined?{}:{body:JSON.stringify(body)})});
  } catch {throw new ShoppingError('SHOP_SERVICE_UNAVAILABLE',503);}
  const value=await response.json().catch(()=>null);
  if(!response.ok || value===null) throw new ShoppingError(value?.error?.code ?? 'SHOP_SERVICE_UNAVAILABLE',response.status>=400?response.status:503);
  return value as T;
}

export async function loadShopping(context:GetServerSidePropsContext):Promise<GetServerSidePropsResult<ShoppingPage>> {
  context.res.setHeader('Cache-Control',noStore);
  context.res.setHeader('X-Robots-Tag','noindex');
  context.res.setHeader('Referrer-Policy','no-referrer');
  const url=new URL(context.resolvedUrl,'http://shopping.invalid');
  // Retired entry settings are never reflected into public hydration state.
  const legacyEntry=['user_id','policy','config','agent','task_id','client_run_id','v'].some(key=>url.searchParams.has(key));
  for(const key of ['user_id','policy','config','agent','task_id','client_run_id','v'])url.searchParams.delete(key);
  const rawId=context.params?.sessionId;
  const sessionId=typeof rawId==='string'?rawId:null;
  const prefix=sessionId?`/s/${encodeURIComponent(sessionId)}`:'';
  const path=(sessionId?url.pathname.slice(prefix.length):url.pathname) || '/';
  const props:ShoppingPage={sessionId,session:null,result:null,product:null,cart:null,reviews:null,
    reviewPage:1,error:null,viewId:randomUUID()};
  try {
    if(!sessionId) {
      // Logging this lookup does not create an anonymous session or a rollout.
      const restored=await request<ShopSessionResponse>(context,null,'/session');
      const cookie=context.req.cookies[cookieName()];
      if(!cookie || !restored) throw new ShoppingError('SESSION_REQUIRED',401);
      const blocked=['/api','/admin','/internal','/docs','/openapi'];
      if(blocked.some(value=>path===value||path.startsWith(value+'/'))) throw new ShoppingError('PAGE_NOT_FOUND',404);
      if(legacyEntry) throw new ShoppingError('SESSION_URL_REQUIRED',400);
      return {redirect:{destination:`/s/${encodeURIComponent(cookie)}${path}${url.search}`,permanent:false}};
    }
    if(!/^[A-Za-z0-9_-]{43}$/.test(sessionId)) {
      // Still ask the backend so failed/out-of-session attempts have a server record.
      await request(context,sessionId,'/session');
      throw new ShoppingError('INVALID_SESSION',401);
    }
    props.session=await request<ShopSessionResponse>(context,sessionId,'/session');
    props.viewId=props.session.viewId;
    if(legacyEntry) throw new ShoppingError('SESSION_URL_REQUIRED',400);
    const secure=(process.env.RECARENA_SHOP_URL ?? '').startsWith('https://');
    context.res.setHeader('Set-Cookie',`${cookieName()}=${sessionId}; Path=/; HttpOnly; SameSite=Lax${secure?'; Secure':''}`);
    if(props.session.status!=='active') {
      context.res.statusCode=410;
      return {props};
    }
    if(path==='/cart') {
      props.cart=await request<BrowserCart>(context,sessionId,`/cart?viewId=${encodeURIComponent(props.viewId)}`);
    } else if(path==='/search') {
      const query=url.searchParams.get('q') ?? '';
      if(!query.trim()) throw new ShoppingError('MISSING_QUERY',400);
      const submitted=url.searchParams.get('request');
      const requestId=submitted && /^[0-9a-f-]{36}$/i.test(submitted)?submitted:randomUUID();
      props.result=await request<SearchResponse>(context,sessionId,'/search',{
        viewId:props.viewId,query,requestKey:requestId});
    } else if(path.startsWith('/results/')) {
      props.result=await request<SearchResponse>(context,sessionId,path+url.search);
    } else if(path.startsWith('/products/')) {
      const productId=path.slice('/products/'.length);
      if(!productId || productId.includes('/')) throw new ShoppingError('PAGE_NOT_FOUND',404);
      const params=new URLSearchParams({viewId:url.searchParams.get('view') ?? props.viewId});
      const item=url.searchParams.get('item');
      if(item)params.set('item',item);
      props.product=await request<ProductDetail>(context,sessionId,`/products/${productId}?${params}`);
      const page=Number(url.searchParams.get('review_page') ?? 1);
      if(!Number.isSafeInteger(page)||page<1)throw new ShoppingError('INVALID_REVIEW_PAGE',400);
      props.reviewPage=page;
      props.reviews=await request<ReviewsResponse>(context,sessionId,
        `/products/${productId}/reviews?viewId=${encodeURIComponent(props.product.viewId)}&offset=${(page-1)*5}&limit=5`);
    } else if(path!=='/') throw new ShoppingError('PAGE_NOT_FOUND',404);
  } catch(error) {
    props.error=error instanceof ShoppingError?error.code:'SHOP_SERVICE_UNAVAILABLE';
    context.res.statusCode=error instanceof ShoppingError?error.status:503;
  }
  props.viewId=props.cart?.viewId??props.result?.viewId??props.product?.viewId??props.viewId;
  return {props};
}
