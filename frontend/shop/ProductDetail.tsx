import React,{FormEvent,useState} from 'react';
import type {BrowserProduct as ProductDetail,BrowserReviews as ReviewsResponse} from '../generated/api';
import {api} from '../shared/api';
import {uuid} from '../shared/uuid';
import {text} from './strings';
import {Stars,compactReviewCount} from './Rating';
import {Price} from './Price';
import {activateOnSpace,moveRadio,SubmitButton} from './controls';
import type {Telemetry,PageMeasurement} from './telemetry';
import {ProductReviews} from './ProductReviews';
import {ProductGallery} from './ProductGallery';
import {Availability} from './Availability';
import {QuantitySelect} from './QuantitySelect';

function ProductAccordion({id,title,children}:{id:string;title:string;children:React.ReactNode}) {
  const [expanded,setExpanded]=useState(false);
  const contentId=`${id}-content`;
  return <div id={id} className="a-section a-spacing-none a-expander-container product-accordion">
    <h2><a className="a-expander-header a-expander-section-header a-link-section-expander" href={`#${contentId}`} role="button" aria-expanded={expanded} aria-controls={contentId} onKeyDown={activateOnSpace}
      onClick={event=>{event.preventDefault();setExpanded(value=>!value);}}><i className={`a-icon a-icon-section-${expanded?'collapse':'expand'}`} aria-hidden="true"/><span className="a-expander-prompt">{title}</span></a></h2>
    <div id={contentId} className="a-expander-content a-expander-section-content a-section-expander-inner" data-expanded={expanded} hidden={!expanded}>{children}</div>
  </div>;
}

export function Detail({ product, base, initialReviews, initialReviewPage, maxQuantity, disabled, buy, add, onError, telemetry, measurement }: {product: ProductDetail; base:string; initialReviews:ReviewsResponse; initialReviewPage:number; maxQuantity: number; disabled: boolean;
  add?: (p:string,v:string,q:number,origin:string|null)=>Promise<void>;
  telemetry:Telemetry;measurement:PageMeasurement;
  buy: (p: string, v: string, q: number, origin: string | null) => Promise<void>; onError: (message: string) => void}) {
  const [variantId, setVariantId] = useState(product.selection?.variant_id ?? (product.variants.length === 1 ? product.variants[0].variant_id : ''));
  const [quantity, setQuantity] = useState(String(product.selection?.quantity ?? 1));
  const [saving, setSaving] = useState(false);
  const variant = product.variants.find(v => v.variant_id === variantId);
  const quantityLimit = Math.min(maxQuantity,30);
  const count = Number(quantity);
  const validQuantity = Number.isInteger(count) && count >= 1 && count <= quantityLimit;
  const images = variant?.image_urls.length ? variant.image_urls : product.image_urls;
  const attributes = { ...product.attributes, ...variant?.attributes_override };

  async function saveSelection(id: string, nextQuantity: string) {
    if (!id || !Number.isInteger(Number(nextQuantity)) || Number(nextQuantity) < 1 || Number(nextQuantity) > quantityLimit) return;
    setSaving(true);
    try { await api(`/products/${product.product_id}/selection`, { method: 'PUT', body: JSON.stringify({requestKey:uuid(),viewId:product.viewId,variant_id: id, quantity: Number(nextQuantity) }) },base); }
    catch (e) { onError((e as Error).message); }
    finally { setSaving(false); }
  }

  const categories=product.categories.filter(category=>category.trim());
  const dimensions=[...new Set(product.variants.flatMap(value=>Object.keys(value.option_values)))];
  // Each choice resolves to a real catalog variant. Prefer preserving the other
  // selected values; do not create combinations or keep a second selection state.
  function variantFor(dimension:string,value:string) {
    const matches=product.variants.filter(item=>item.option_values[dimension]===value);
    const available=matches.filter(item=>item.is_available&&item.is_purchasable);
    const choices=available.length?available:matches;
    const matchingValues=(item:ProductDetail['variants'][number])=>dimensions.filter(key=>key!==dimension&&variant?.option_values[key]===item.option_values[key]).length;
    return choices.reduce((best,item)=>!best||matchingValues(item)>matchingValues(best)?item:best,choices[0]);
  }
  function chooseVariant(id:string,element:HTMLElement) {
    if(disabled||saving||id===variantId)return;
    setVariantId(id);
    void saveSelection(id,quantity).then(()=>requestAnimationFrame(()=>{
      if(document.activeElement===document.body)element.focus();
    }));
  }
  function submitPurchase(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(disabled||saving||!variant?.is_purchasable||!validQuantity)return;
    const submitter=(event.nativeEvent as SubmitEvent).submitter as HTMLInputElement|null;
    if(submitter?.name==='submit.add-to-cart'&&add)void add(product.product_id,variantId,count,null);
    else void buy(product.product_id,variantId,count,null);
  }
  const displayPrice=(labelId:string)=>variant
    ? <Price amount={variant.unit_price_minor} currency={variant.currency} labelId={labelId}/>
    : product.variants.length>0&&product.variants.every(v=>v.unit_price_minor===null)
      ? 'Price not provided' : 'Select an option to see its price';

  return <>{categories.length>0&&<div id="wayfinding-breadcrumbs_feature_div"><ul>
    {categories.map((category,index)=><React.Fragment key={index}>
      {index>0&&<li className="a-breadcrumb-divider" role="presentation" aria-hidden="true"><span className="a-list-item">›</span></li>}
      <li><span className="a-list-item">{category}</span></li>
    </React.Fragment>)}
  </ul></div>}
  <div id="ppd" className="product-detail">
    <div id="rightCol" className="product-buybox" aria-label="Purchase options">
      <form id="addToCart" className="detail-purchase-actions" method="post" action={`${base}/api/shop/v1/${add?'cart/items':'purchases'}`} onSubmit={submitPurchase}>
        <div id="buybox-price" className="price">{displayPrice('buybox-price-accessibility-label')}</div>
        <div id="availability" className="a-section product-availability"><Availability available={variant?.is_available} purchasable={variant?.is_purchasable}/></div>
        <QuantitySelect value={quantity} max={quantityLimit} disabled={disabled||saving} valid={validQuantity}
          onChange={value=>{setQuantity(value);void saveSelection(variantId,value);}}/>
        {!validQuantity && <p role="alert">Choose a whole quantity from 1 to {quantityLimit}.</p>}
        <input type="hidden" name="ASIN" value={product.product_id}/><input type="hidden" name="items[0.base][asin]" value={product.product_id}/>
        <input type="hidden" name="items[0.base][quantity]" value={quantity}/>
        {add&&<SubmitButton id="add-to-cart-button" name="submit.add-to-cart" label={text.add} title="Add to Shopping Cart"
          announceId="submit.add-to-cart-announce" disabled={disabled||saving||!variant?.is_purchasable||!validQuantity}/>}
        <SubmitButton id="buy-now-button" name="submit.buy-now" label="Buy Now" title="Buy Now" announceId="submit.buy-now-announce"
          formAction={`${base}/api/shop/v1/purchases`} disabled={disabled||saving||!variant?.is_purchasable||!validQuantity}/>
      </form>
    </div>
    <ProductGallery key={variantId||product.product_id} images={images} title={product.title}/>
    <div id="centerCol" className="centerColAlign product-information"><h1 id="title" className="a-spacing-none"><span id="productTitle">{product.title}</span></h1>
      {product.brand?.trim()&&<div id="bylineInfo" className="brand-name">Brand: {product.brand}</div>}
      <div id="averageCustomerReviews" className="rating-summary" data-asin={product.product_id}>
        {product.rating===null?<span>No ratings</span>:<span id="acrPopover"><a role="button" href="#customerReviews" onKeyDown={activateOnSpace}>
          <span className="a-size-small a-color-base" aria-hidden="true">{product.rating.toFixed(1)}{'\u00a0'}</span><Stars value={product.rating} size="mini"/></a></span>}{' '}
        <a id="acrCustomerReviewLink" href="#customerReviews"><span id="acrCustomerReviewText" aria-label={`${product.review_count.toLocaleString('en-US')} Reviews`}>({compactReviewCount(product.review_count)})</span></a>
      </div>
      <hr className="a-divider-normal"/>
      <div id="corePriceDisplay_desktop_feature_div" className="price product-information-price">{displayPrice('apex-pricetopay-accessibility-label')}</div>
      {product.variants.length>1?(dimensions.length?dimensions:['Options']).map((dimension,groupIndex)=>{
        const choices=dimensions.length?[...new Set(product.variants.map(value=>value.option_values[dimension]).filter((value):value is string=>value!==undefined))].map(value=>({label:value,item:variantFor(dimension,value)}))
          :product.variants.map(item=>({label:item.variant_id,item}));
        const firstAvailable=choices.findIndex(({item})=>item.is_available&&item.is_purchasable);
        const selected=dimensions.length?variant?.option_values[dimension]:variantId;
        const id=`option-${groupIndex}`;
        return <div id={`inline-twister-row-${id}`} className="variant-options" key={dimension}>
          <span>{dimension}: </span><span className="a-text-bold" id={`inline-twister-expanded-dimension-text-${id}`}>{selected||'Select an option'}</span>
          <ul role="radiogroup" aria-label={dimension}>{choices.map(({label,item},index)=>{
            const checked=selected===label;
            return <li key={label}><span className={`a-button a-button-toggle${checked?' a-button-selected':''}`}>
              <span className="a-button-inner">
                <input className="a-button-input" type="submit" role="radio" id={`variant-choice-${groupIndex}-${index}`} value={label} aria-checked={checked}
                  aria-labelledby={`${id}_${index}-announce`} tabIndex={checked||(!selected&&index===firstAvailable)?0:-1}
                  disabled={disabled||saving||!item.is_available||!item.is_purchasable} onKeyDown={moveRadio}
                  onClick={event=>{event.preventDefault();chooseVariant(item.variant_id,event.currentTarget);}}/>
                <span className="a-button-text" id={`${id}_${index}-announce`} aria-hidden="true"><span className="a-text-bold">{label}</span>
                  <span className="variant-price"><Price amount={item.unit_price_minor} currency={item.currency}/></span>
                  {(!item.is_available||!item.is_purchasable)&&<span>Currently unavailable.</span>}
                </span>
              </span>
            </span></li>;
          })}</ul>
        </div>;
      }):variant&&Object.keys(variant.option_values).length>0&&<div className="single-option-values">
        {Object.entries(variant.option_values).map(([key,value])=><div key={key}><span>{key}: </span><span>{value}</span></div>)}
      </div>}
      <div className="product-accordions">
        {product.features.length>0&&<ProductAccordion id="feature-bullets" title="About this item">
          <ul>{product.features.map((feature,index)=><li key={index}><span className="a-list-item">{feature}</span></li>)}</ul>
        </ProductAccordion>}
        {Object.keys(attributes).length>0&&<ProductAccordion id="detailBulletsWrapper_feature_div" title="Product details">
          <div id="detailBullets_feature_div"><table className="a-keyvalue product-facts"><tbody>{Object.entries(attributes).map(([key,value])=><tr key={key}>
            <th scope="row" className="a-color-secondary">{key}</th><td><span>{typeof value==='object'?JSON.stringify(value):String(value)}</span></td>
          </tr>)}</tbody></table></div>
        </ProductAccordion>}
      </div>
    </div>
  </div>
    {product.description&&<div className="product-more-information"><h2>Product description</h2><div id="productDescription"><p><span>{product.description}</span></p></div></div>}
    <ProductReviews product={product} base={base} initialReviews={initialReviews} initialReviewPage={initialReviewPage}
      telemetry={telemetry} measurement={measurement}/>
  </>;
}
