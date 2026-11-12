import type {BrowserProduct,BrowserReviews,BrowserResults,BrowserSession,BrowserCart} from '../generated/api';

// Only public shopping DTOs cross the server/client boundary.
export type ShoppingPage = {
  sessionId:string|null;
  session:BrowserSession|null;
  result:BrowserResults|null;
  product:BrowserProduct|null;
  cart:BrowserCart|null;
  reviews:BrowserReviews|null;
  reviewPage:number;
  error:string|null;
  viewId:string;
};
