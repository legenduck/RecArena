export function Price({amount,currency,labelId}:{amount:number|null;currency:string;labelId?:string}) {
  if(amount===null)return <>Price not provided</>;
  const format=new Intl.NumberFormat('en-US',{style:'currency',currency});
  const parts=format.formatToParts(amount/100);
  const symbol=parts.find(part=>part.type==='currency')?.value??currency;
  const whole=parts.filter(part=>part.type==='integer'||part.type==='group').map(part=>part.value).join('');
  const decimal=parts.find(part=>part.type==='decimal')?.value??'';
  const fraction=parts.find(part=>part.type==='fraction')?.value;
  return <>{labelId&&<span className="aok-offscreen" id={labelId}>{format.format(amount/100)}</span>}
    <span className="a-price price-amount"><span className="a-offscreen">{labelId?'':format.format(amount/100)}</span>
      <span aria-hidden="true"><span className="a-price-symbol price-currency">{symbol}</span>
        <span className="a-price-whole price-whole">{whole}<span className="a-price-decimal">{decimal}</span></span>
        {fraction!==undefined&&<span className="a-price-fraction price-fraction">{fraction}</span>}
      </span>
    </span></>;
}
