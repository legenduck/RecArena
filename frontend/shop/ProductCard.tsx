import React from 'react';
import type {BrowserCard as ProductCard} from '../generated/api';
import {uuid} from '../shared/uuid';
import {text} from './strings';
import type {Telemetry,PageMeasurement,ListPresentation} from './telemetry';
import {Rating,compactReviewCount} from './Rating';
import {Price} from './Price';
import {SubmitButton} from './controls';
import {cardImageSources} from './imageSources';

export function Card({ card, position, base, disabled, navigate, buy, cartEnabled, telemetry, measurement, presentation, viewId, blockId }: {card: ProductCard; position:number; base:string; disabled: boolean; cartEnabled:boolean; navigate: (p: string) => void;
  telemetry:Telemetry;measurement:PageMeasurement;viewId:string;blockId:string;
  presentation:ListPresentation;
  buy: (p: string, v: string, q: number, origin: string | null) => Promise<void>}) {
  const [failedImage, setFailedImage] = React.useState<string>();
  const image = failedImage === card.image_url ? {src: card.image_url} : cardImageSources(card.image_url);
  const imageElement = React.useRef<HTMLImageElement>(null);
  React.useEffect(() => {
    // The SSR image request can fail before hydration attaches onError.
    const element = imageElement.current;
    if (image.srcSet && element?.complete && element.naturalWidth === 0) setFailedImage(card.image_url);
  }, [card.image_url, image.srcSet]);
  const href = `${base}/products/${encodeURIComponent(card.product_id)}?view=${viewId}&item=${encodeURIComponent(card.item_key)}`;
  const payload={item_key:card.item_key,block_id:blockId,list_presentation_id:presentation.id};
  const click=()=>telemetry.emit(measurement,'product_clicked',payload,uuid(),viewId);
  const open=(event:React.MouseEvent<HTMLAnchorElement>,target=href)=>{
    click();if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    event.preventDefault();navigate(target);
  };
  const auxiliary=(event:React.MouseEvent<HTMLAnchorElement>)=>{if(event.button===1)click();};
  const reviewsHref=href+'#customerReviews';
  return <div role="listitem" className="s-result-item s-asin product-card" data-asin={card.product_id} data-index={position} data-component-type="s-search-result">
    <div className="sg-col-inner"><div className="s-card-container" data-cy="asin-faceout-container">
      <div data-cy="image-container" className="card-image s-product-image-container"><span data-component-type="s-product-image">
        <a href={href} aria-hidden="true" tabIndex={-1} onClick={e=>open(e)} onAuxClick={auxiliary}>
          <div className="a-section aok-relative s-image-square-aspect">
            <img ref={imageElement} className="s-image" src={image.src} srcSet={image.srcSet} alt={card.title} aria-hidden="true"
              onError={image.srcSet ? () => setFailedImage(card.image_url) : undefined}/>
          </div>
        </a></span></div>
      <div data-cy="title-recipe" className="a-spacing-small"><a className="product-card-link" href={href} onClick={e=>open(e)} onAuxClick={auxiliary}>
        <h2 className="a-color-base a-spacing-none" aria-label={card.title}><span>{card.title}</span></h2></a></div>
      <div data-cy="reviews-block" className="card-rating rating-summary">
        <Rating value={card.rating} href={reviewsHref} onClick={e=>open(e,reviewsHref)} onAuxClick={auxiliary}/>
        <a href={reviewsHref} aria-label={`${card.review_count.toLocaleString('en-US')} ratings`} onClick={e=>open(e,reviewsHref)} onAuxClick={auxiliary}>
          <span aria-hidden="true">({compactReviewCount(card.review_count)})</span></a>
      </div>
      <div data-cy="price-recipe" className="price"><span className="aok-offscreen">Price, product page</span>
        <a href={href} onClick={e=>open(e)} onAuxClick={auxiliary}><Price amount={card.price.min_minor} currency={card.price.currency}/>
          {card.price.max_minor!==card.price.min_minor&&<><span className="price-range-separator"> – </span><Price amount={card.price.max_minor} currency={card.price.currency}/></>}
        </a></div>
      <div data-cy="add-to-cart" className="a-button-stack">{card.requires_option_selection
        ? <a className="button-link purchase-button" href={href} onClick={e=>open(e)} onAuxClick={auxiliary}>{text.chooseOptions}</a>
        : <form method="post" action={`${base}/api/shop/v1/${cartEnabled?'cart/items':'purchases'}`}
            onSubmit={event=>{event.preventDefault();if(!disabled)void buy(card.product_id,card.default_variant_id!,1,card.item_key);}}>
            <input type="hidden" name="items[0.base][asin]" value={card.product_id}/><input type="hidden" name="items[0.base][quantity]" value="1"/>
            <SubmitButton label={cartEnabled?text.add:'Buy Now'} name={cartEnabled?'submit.addToCart':'submit.buy-now'} disabled={disabled}/>
          </form>}
      </div>
    </div></div>
  </div>;
}
