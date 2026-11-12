import type {Environment} from './types';


function summary(environment:Environment) {
  const config=environment.config;
  const families=[...new Set(config.ranking_sources?Object.values(config.ranking_sources).map(source=>source.policy.family):config.policy?[config.policy.family]:[])];
  const parts=[families.join(' + ')||'Environment'];
  const pageSize=config.layout?.main_page_size??config.main_page_size;
  if(pageSize!==undefined)parts.push(`${pageSize} items/page`);
  const blocks=config.layout?.blocks??[];
  const columns=[...new Set(blocks.filter(block=>block.component==='grid').map(block=>'columns' in block?block.columns:undefined).filter(value=>value!==undefined))];
  if(columns.length===1)parts.push(`${columns[0]} columns`);
  if(blocks.length>1)parts.push(`${blocks.length} sections`);
  return parts.join(' · ');
}

// Display labels do not change environment IDs, URL aliases or frozen settings.
export function environmentLabel(environment:Environment,environments:Environment[]=[]) {
  const label=summary(environment);
  const matching=environments.filter(item=>summary(item)===label);
  return matching.length>1?`${label} · saved entry ${matching.findIndex(item=>item.id===environment.id)+1}`:label;
}
