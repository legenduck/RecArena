export class ApiError extends Error {
  constructor(public code: string, message: string, public retryable=false) { super(`${message} (${code})`); }
}

export async function api<T>(path: string, options: RequestInit = {}, sessionPrefix = ''): Promise<T> {
  let response:Response;
  try {
    response=await fetch(sessionPrefix + '/api/shop/v1' + path, {
      ...options, headers: { 'Content-Type': 'application/json', ...options.headers },
    });
  } catch (error) {
    if (error instanceof Error && error.name==='AbortError') throw error;
    throw new ApiError('SHOP_SERVICE_UNAVAILABLE','Cannot connect to the shopping service. Please try again.',true);
  }
  let body:unknown;
  try {body=await response.json();}
  catch {
    if(response.status>=500 || response.status===429)
      throw new ApiError('SHOP_SERVICE_UNAVAILABLE','The shopping service is unavailable. Please try again.',true);
    throw new ApiError('INVALID_API_RESPONSE','The shopping service returned an incomplete response. Please try again.',true);
  }
  if (body===null || typeof body!=='object' || Array.isArray(body))
    throw new ApiError('INVALID_API_RESPONSE','The shopping service returned an invalid response. Please try again.',true);
  if (!response.ok) {
    const failure=(body as {error?:{code?:string;message?:string}}).error;
    throw new ApiError(failure?.code ?? 'REQUEST_FAILED',failure?.message ?? 'Request failed.',response.status>=500 || response.status===429);
  }
  return body as T;
}

export const money = (amount: number | null, currency: string) =>
  amount === null ? 'Price not provided' : new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount / 100);
