import type {NextApiRequest,NextApiResponse} from 'next';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';

// Keep the public proxy narrower than the backend's research/control API.
function allowedShoppingPath(method:string,parts:string[]) {
  if(parts[0]!=='v1')return false;
  const path=parts.slice(1);
  const read=method==='GET'||method==='HEAD';
  if(path[0]==='cart') {
    if(path.length===1)return read;
    if(path.length===2)return method==='POST'&&['items','checkout'].includes(path[1]);
    return path.length===3&&path[1]==='items'&&['PUT','DELETE'].includes(method);
  }
  if(path.length===1) {
    if(path[0]==='session')return read;
    return method==='POST'&&['search','purchases','abandon'].includes(path[0]);
  }
  if(path[0]==='events')return method==='POST'&&path.length===2&&path[1]==='batch';
  if(path[0]==='results')return read&&(path.length===2||(path.length===4&&path[2]==='blocks'));
  if(path[0]==='products')return (read&&(path.length===2||(path.length===3&&path[2]==='reviews')))
    ||(method==='PUT'&&path.length===3&&path[2]==='selection');
  return false;
}

export async function proxyShopping(req:NextApiRequest,res:NextApiResponse,kind:'shop'|'assets') {
  res.setHeader('X-Robots-Tag','noindex');
  res.setHeader('Cache-Control','no-store');
  const id=req.query.sessionId;
  const parts=req.query.path;
  if(typeof id!=='string'||!Array.isArray(parts)||parts.some(part=>part==='.'||part==='..'||/[\\/]/.test(part))) {
    res.status(400).json({error:{code:'INVALID_PATH',message:'Invalid shopping path.'}});return;
  }
  if(kind==='shop'?!allowedShoppingPath(req.method??'',parts):
    !(['GET','HEAD'].includes(req.method??'')&&parts.length===1)) {
    res.status(404).json({error:{code:'NOT_FOUND',message:'Page not found.'}});return;
  }
  const base=(process.env.RECARENA_PLATFORM_URL??'http://127.0.0.1:8010').replace(/\/$/,'');
  const url=new URL(`${base}/s/${encodeURIComponent(id)}/${kind==='shop'?'api/shop':'assets'}/${parts.map(encodeURIComponent).join('/')}`);
  for(const [key,value] of Object.entries(req.query)) {
    if(key==='sessionId'||key==='path'||value===undefined)continue;
    for(const item of Array.isArray(value)?value:[value])url.searchParams.append(key,item);
  }
  const headers:Record<string,string>={'User-Agent':req.headers['user-agent']??'','X-RecArena-Response-Kind':'data_api'};
  for(const key of ['content-type','idempotency-key','if-none-match','if-modified-since','origin']) {
    const value=req.headers[key];if(typeof value==='string')headers[key]=value;
  }
  try {
    let body:Buffer|undefined;
    if(req.method!=='GET'&&req.method!=='HEAD') {
      const chunks:Buffer[]=[];let size=0;
      for await(const chunk of req) {
        size+=chunk.length;
        if(size>512*1024){res.status(413).json({error:{code:'REQUEST_TOO_LARGE',message:'Request too large.'}});return;}
        chunks.push(Buffer.from(chunk));
      }
      body=Buffer.concat(chunks);
    }
    const upstream=await fetch(url,{method:req.method,headers,body,cache:'no-store',redirect:'manual'});
    res.status(upstream.status);
    for(const key of ['content-type','cache-control','etag','last-modified','vary','x-robots-tag','content-security-policy','x-content-type-options','referrer-policy']) {
      const value=upstream.headers.get(key);if(value)res.setHeader(key,value);
    }
    if(req.method==='HEAD'||!upstream.body){res.end();return;}
    await pipeline(Readable.fromWeb(upstream.body as never),res);
  } catch {
    if(!res.headersSent)res.status(503).json({error:{code:'SHOP_SERVICE_UNAVAILABLE',message:'Shopping service unavailable.'}});
    else res.end();
  }
}
