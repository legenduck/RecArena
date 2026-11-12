import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {useRouter} from 'next/router';
import type {BrowserProduct as ProductDetail,BrowserReviews as ReviewsResponse} from '../generated/api';
import {api} from '../shared/api';
import {uuid} from '../shared/uuid';
import {Stars} from './Rating';
import {Pagination} from './Pagination';
import {ReviewSummary} from './ReviewSummary';
import type {Telemetry,PageMeasurement} from './telemetry';

const REVIEWS_PER_PAGE=5;

export function ProductReviews({product,base,initialReviews,initialReviewPage,telemetry,measurement}:{
  product:ProductDetail; base:string; initialReviews:ReviewsResponse; initialReviewPage:number;
  telemetry:Telemetry; measurement:PageMeasurement;
}) {
  const router=useRouter();
  const [reviews, setReviews] = useState<ReviewsResponse | null>(initialReviews);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewPage, setReviewPage] = useState(initialReviewPage);
  const [reviewError, setReviewError] = useState('');
  const [reviewRetry, setReviewRetry] = useState(0);
  const reviewElement=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(reviewPage===initialReviewPage&&reviewRetry===0){setReviews(initialReviews);return;}
    const controller = new AbortController();
    setReviewBusy(true); setReviewError(''); setReviews(null);
    api<ReviewsResponse>(`/products/${product.product_id}/reviews?viewId=${product.viewId}&offset=${(reviewPage-1)*REVIEWS_PER_PAGE}&limit=${REVIEWS_PER_PAGE}`,
      {signal:controller.signal},base)
      .then(value=>{if (!controller.signal.aborted) setReviews(value);})
      .catch(error=>{if (!controller.signal.aborted) setReviewError(error.message);})
      .finally(()=>{if (!controller.signal.aborted) setReviewBusy(false);});
    return ()=>controller.abort();
  },[product.product_id,product.viewId,reviewPage,reviewRetry]);
  useLayoutEffect(()=>{
    if (!reviews || measurement.reviews.has(reviews.viewId)) return;
    measurement.reviews.add(reviews.viewId);
    telemetry.emit(measurement,'reviews_rendered',{review_ids:reviews.reviews.map(r=>r.review_id)},uuid(),reviews.viewId);
  },[reviews,reviewPage,product.product_id,measurement,telemetry]);
  useEffect(()=>{
    let intersecting=false;
    let visible=false;
    const update=()=>{
      const next=intersecting && document.visibilityState==='visible';
      if (next && !visible) telemetry.emit(measurement,'review_section_entered',{});
      visible=next;
    };
    const observer=new IntersectionObserver(entries=>{
      intersecting=entries[entries.length-1].isIntersecting;update();
    });
    if(reviewElement.current) observer.observe(reviewElement.current);
    document.addEventListener('visibilitychange',update);
    return ()=>{observer.disconnect();document.removeEventListener('visibilitychange',update);};
  },[product.product_id,telemetry,measurement]);
  function reviewHref(page:number) {
    const params=new URLSearchParams({view:product.viewId,review_page:String(page)});
    return `${base}/products/${product.product_id}?${params}`;
  }
  function changeReviewPage(page:number) {
    setReviewPage(page);
    void router.push(reviewHref(page),undefined,{shallow:true,scroll:false});
    reviewElement.current?.scrollIntoView({block:'start'});
  }

  return <div id="customerReviews" className="reviews" ref={reviewElement} aria-busy={reviewBusy}>
      <ReviewSummary product={product}/>
      <div className="review-list"><div className="reviews-heading"><p className="review-sort">Newest first</p></div>
      {reviewBusy && <p role="status">Loading reviews…</p>}
      {reviewError && <div className="error" role="alert"><p>{reviewError}</p><button type="button" onClick={()=>setReviewRetry(value=>value+1)}>Try again</button></div>}
      {reviews?.reviews.map(review=><div key={review.review_id} id={review.review_id} data-hook="review" data-review-id={review.review_id}>
        <div data-hook="genome-widget"><span className="a-profile" data-a-size="small">
          <span className="a-profile-avatar-wrapper" aria-hidden="true"><span className="a-profile-avatar">
            <img src="/reviewer-avatar.svg" alt="" width={34} height={34}/>
          </span></span>
          <span className="a-profile-content"><span className="a-profile-name">{review.display_author_alias}</span></span>
        </span></div>
        <div className="a-row review-heading"><Stars value={review.rating} hook="review-star-rating"/><h5 data-hook="reviewTitle">{review.title}</h5></div>
        <span data-hook="review-date">Reviewed on {new Date(review.timestamp_utc).toLocaleDateString('en-US',{timeZone:'UTC',month:'long',day:'numeric',year:'numeric'})}</span>
        {review.verified_purchase===true&&<span data-hook="avp-badge">Verified Purchase</span>}
        <div data-hook="reviewTextContainer"><div data-hook="reviewText"><span>{review.body}</span></div></div>
      </div>)}
      {reviews && !reviews.reviews.length && <p>No reviews available.</p>}
      {product.review_count > REVIEWS_PER_PAGE && <Pagination page={reviewPage}
        pages={Math.ceil(product.review_count/REVIEWS_PER_PAGE)} disabled={reviewBusy || Boolean(reviewError)} hrefFor={reviewHref} onChange={changeReviewPage}/>}
      </div>
    </div>;
}
