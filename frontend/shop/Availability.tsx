/** Display the catalog's purchase availability; do not invent stock for missing data. */
export function Availability({available,purchasable}:{available?:boolean|null;purchasable?:boolean|null}) {
  if(available==null||purchasable==null)return null;
  const inStock=available&&purchasable;
  return <span className={`primary-availability-message ${inStock?'a-color-success':'a-color-secondary'}`}>
    {inStock?'In Stock':'Currently unavailable.'}
  </span>;
}
