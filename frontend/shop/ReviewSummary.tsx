import type {BrowserProduct} from '../generated/api';
import {Stars} from './Rating';
import {text} from './strings';

type ReviewTotals = Pick<BrowserProduct, 'rating' | 'review_count' | 'rating_distribution'>;

export function ReviewSummary({product}: {product: ReviewTotals}) {
  const counts = new Map((product.rating_distribution ?? []).map(bucket => [bucket.rating, bucket.count]));
  const ratings = [...new Set([5, 4, 3, 2, 1, ...counts.keys()])].sort((a, b) => b - a);
  const available = product.rating_distribution != null &&
    [...counts.values()].reduce((sum, count) => sum + count, 0) === product.review_count;

  return <div className="review-summary">
    <h2>{text.reviews}</h2>
    <div className="review-summary-rating">
      {product.rating !== null && <Stars value={product.rating} hidden size="medium" hook="average-star-rating"/>}
      <span data-hook="rating-out-of-text">{product.rating === null ? 'No ratings' : `${product.rating.toFixed(1)} out of 5`}</span>
    </div>
    <span data-hook="total-review-count">{product.review_count.toLocaleString('en-US')} ratings</span>
    {available && product.review_count > 0 && <ul id="histogramTable" className="rating-distribution" aria-label="Rating distribution">
      {ratings.map(rating => {
        const count = counts.get(rating) ?? 0;
        const percent = count / product.review_count * 100;
        return <li key={rating} aria-label={`${rating} ${rating === 1 ? 'star' : 'stars'}: ${count.toLocaleString('en-US')} ${count === 1 ? 'rating' : 'ratings'} (${Math.round(percent)}%)`}>
          <span className="a-list-item"><div className="rating-distribution-row" aria-hidden="true">
            <div className="a-section a-spacing-none rating-distribution-label">
              {ratings.map(value=><span className="rating-distribution-column-space" key={value}>{value} star</span>)}
              {rating} star
            </div>
            <div className="a-section a-spacing-none rating-distribution-value"><div className="a-meter rating-distribution-track"><div className="a-meter-bar a-meter-unfilled" style={{width: `${percent}%`}}/></div></div>
            <div className="a-section a-spacing-none rating-distribution-percent">
              {ratings.map(value=><span className="rating-distribution-column-space" key={value}>{Math.round((counts.get(value)??0)/product.review_count*100)}%</span>)}
              {Math.round(percent)}%
            </div>
          </div></span>
        </li>;
      })}
    </ul>}
    {!available && product.review_count > 0 && <p className="review-meta">Rating breakdown unavailable.</p>}
  </div>;
}
