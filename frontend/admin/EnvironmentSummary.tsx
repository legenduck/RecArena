import type {Environment} from './types';
import type {GridBlock,Presentation} from '../generated/control';

export function EnvironmentSummary({environment,presentation}:{environment:Environment;presentation:Presentation}) {
  return <div className="admin-environment-summary" aria-label="Published environment settings">
    <details><summary>Product data bindings</summary>
      <dl className="admin-setting-list">
        <div><dt>Catalog</dt><dd>{environment.dataset_snapshot_id}</dd></div>
        <div><dt>Reviews</dt><dd>{environment.review_snapshot_id}</dd></div>
        <div><dt>User history</dt><dd>{environment.history_snapshot_id}</dd></div>
      </dl>
    </details>
    <h4>Ranking sources</h4>
    {Object.entries(presentation.ranking_sources).map(([id,source])=><section key={id} className="admin-source-summary" aria-label={'Source '+id}>
      <div className="admin-source-heading"><strong>{id}</strong><span>{source.policy.family}</span></div>
      <dl className="admin-setting-list">
        <div><dt>Service</dt><dd>{source.policy.service_id}</dd></div>
        <div><dt>Policy</dt><dd>{source.policy.policy_id}</dd></div>
        <div><dt>Service policy version</dt><dd>{source.policy.version}</dd></div>
      </dl>
      <details><summary>Recorded policy identity and candidate scope</summary>
        <dl className="admin-setting-list">
          <div><dt>Environment policy record</dt><dd>{source.policy_version_id}</dd></div>
          <div><dt>Candidate scope</dt><dd>{source.policy.candidate_scope}</dd></div>
          <div><dt>Candidate limit</dt><dd>{source.policy.candidate_limit}</dd></div>
        </dl>
      </details>
    </section>)}
    <h4>Layout / Sections</h4>
    <p className="admin-layout-summary">Shopping cart: <strong>{presentation.layout.cart_enabled?'On':'Off'}</strong></p>
    <p className="admin-layout-summary">Abandon shopping button: <strong>{presentation.layout.abandon_enabled?'On':'Off'}</strong></p>
    <p className="admin-layout-summary">Search filter sidebar: <strong>{presentation.layout.sidebar_enabled?'On':'Off'}</strong></p>
    <p className="admin-layout-summary"><strong>{presentation.layout.main_page_size}</strong> items per main page</p>
    <div className="table-scroll"><table><thead><tr><th>Section</th><th>Ranking source</th><th>Layout</th><th>Items</th><th>Offset</th><th>Pages</th></tr></thead>
      <tbody>{presentation.layout.blocks.map(block=><tr key={block.id}>
        <td>{block.title}<span className="admin-secondary-value">{block.id}</span></td><td>{block.source}</td>
        <td>{block.component==='paged_row'?'Paged row':`Grid · ${(block as GridBlock).columns} columns`}</td>
        <td>{block.component==='paged_row'?`${block.visible_count} visible / ${block.total_count} total`:(block as GridBlock).count}</td>
        <td>{block.offset??0}</td><td>{block.visibility==='first_page'?'First page':'All pages'}</td>
      </tr>)}</tbody>
    </table></div>
  </div>;
}
