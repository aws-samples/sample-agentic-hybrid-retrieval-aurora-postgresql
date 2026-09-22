import { Link } from 'wouter';
import bundle from '../../../data/evals/references/reviewed_sources.json';

const labels: Record<string, string> = { E: 'Exact', S: 'Substitute', C: 'Complement', I: 'Irrelevant' };

export function ReferenceComparison({ ids }: { ids: string[] }) {
  return <>{bundle.cases.filter(item => ids.includes(item.id)).map(example => {
    const wands = example.dataset === 'wands';
    return <section className="reviewed-reference" key={example.id} aria-label={`${wands ? 'WANDS' : 'ESCI'} comparison`}>
      <div className="reviewed-reference-heading"><div><span>{wands ? 'Wayfair WANDS' : 'Amazon ESCI'} · Source comparison</span><h2>“{example.query}”</h2></div>
        {!wands && <Link className="reviewed-back" href={`/catalog?q=${encodeURIComponent(example.query)}&view=results`}>Try this search →</Link>}
      </div>
      <p>{example.purpose}</p>
      {wands && <p className="reviewed-reference-note">These are separate Wayfair records. The release does not include product photos or original listing links.</p>}
      <div className="reviewed-product-grid">{example.products.map(product => <article className="reviewed-reference-card" key={product.source_product_id}>
        <p className="reviewed-product-id">{wands ? 'WANDS' : 'ESCI'} product {product.source_product_id}</p>
        <h3>{product.display_name}</h3>
        <span className="reviewed-reference-label">Released label: {labels[product.label] ?? product.label}</span>
        <dl className="reviewed-reference-facts">{product.facts.map(fact => <div key={fact.source_token}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>
        <p>{product.reading_note}</p>
        <details><summary>Inspect the original record</summary>
          <p>The source text is preserved. A relevance label applies to its query; it does not guarantee compatibility or personal comfort.</p>
          <pre>{JSON.stringify(product.original, null, 2)}</pre>
          <p>Original judgment: <code>{JSON.stringify(product.original_judgments)}</code></p>
        </details>
      </article>)}</div>
    </section>;
  })}</>;
}
