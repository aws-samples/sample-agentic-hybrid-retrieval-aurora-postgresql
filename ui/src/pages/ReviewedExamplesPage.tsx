import { useEffect, useState } from 'react';
import { Link, useLocation, useSearch } from 'wouter';
import { api } from '../api';
import { productImage } from '../media';
import { reviewedExamples, reviewedSourceMatches, type ReviewedProduct } from '../reviewedExamples';
import type { ProductDetail } from '../types';
import '../reviewed-examples.css';
import { ReferenceComparison } from '../components/ReferenceComparison';

const categories = [
  { id: 'headphones', name: 'Headphones', purpose: 'Calls and focused work' },
  { id: 'chairs', name: 'Chairs', purpose: 'Support through the workday' },
  { id: 'monitors', name: 'Monitors', purpose: 'Room for code and documents' },
];

function ReviewedCard({ review }: { review: ReviewedProduct }) {
  const [product, setProduct] = useState<ProductDetail>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setProduct(undefined); setFailed(false);
    void api.product(review.product_id).then(value => { if (active) setProduct(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [review.product_id]);
  if (failed) return <article className="reviewed-product" role="status">This product could not be loaded. <Link href={`/products/${review.product_id}`}>Open its record</Link> to retry.</article>;
  if (!product) return <article className="reviewed-product" role="status">Loading product details…</article>;
  const current = reviewedSourceMatches(product, review);
  return <article className="reviewed-product">
    <Link href={`/products/${product.product_id}`} className="reviewed-product-photo"><img src={productImage(product)} alt={product.title} width={500} height={400} /></Link>
    <div className="reviewed-product-text">
      <p className="reviewed-product-id">Original listing · {product.sku}</p>
      <h2><Link href={`/products/${product.product_id}`}>{review.display_name}</Link></h2>
      {current ? <>
        <p className="reviewed-product-finding">{review.card_summary}</p>
        <p>{review.assessment}</p>
        <details><summary>Read the supporting text</summary><dl>{review.facts.map((fact, index) => <div key={index}><dt>{fact.label}</dt><dd>“{fact.quote}”</dd></div>)}</dl></details>
        <div className="reviewed-product-unknown"><strong>Still to check</strong><p>{review.still_unknown}</p></div>
      </> : <p role="alert">This product record has changed since the review. Open the current record before using the saved comparison.</p>}
      <a href={product.listing_url ?? undefined} target="_blank" rel="noreferrer">Original product listing ↗</a>
    </div>
  </article>;
}

export function ReviewedExamplesPage() {
  const search = useSearch();
  const requested = new URLSearchParams(search).get('case');
  const [, navigate] = useLocation();
  const selectCase = (id: string) => navigate(`/labs/examples?case=${id}`);
  const example = reviewedExamples.cases.find(item => item.id === requested) ?? reviewedExamples.cases[0];
  return <div className="reviewed-examples">
    <Link href="/labs/retrieval" className="reviewed-back">← Hybrid retrieval</Link>
    <header><h1>Look beyond the first match.</h1><p>Read the requirement. Compare the original products. Check what their records actually establish.</p></header>
    <nav className="reviewed-categories" aria-label="Alex’s three needs">{categories.map(category => <button key={category.id} type="button" aria-pressed={example.category === category.id} onClick={() => selectCase(reviewedExamples.cases.find(item => item.category === category.id)!.id)}><strong>{category.name}</strong><span>{category.purpose}</span></button>)}</nav>
    <nav aria-label="Reviewed examples">{reviewedExamples.cases.filter(item => item.category === example.category).map(item => <button key={item.id} type="button" aria-pressed={example.id === item.id} onClick={() => selectCase(item.id)}>{item.label}</button>)}</nav>
    <section aria-labelledby="reviewed-need"><div className="reviewed-brief"><span>{example.exercise_kind === 'required' ? 'From the three labs' : 'Optional comparison'}</span><h2 id="reviewed-need">{example.title}</h2><p>{example.need}</p><ul aria-label="Requirements">{example.requirements.map(requirement => <li key={requirement}>{requirement}</li>)}</ul></div>
      <div className="reviewed-product-grid">{example.products.map(product => <ReviewedCard key={product.product_id} review={product} />)}</div>
    </section>
    <ReferenceComparison ids={example.reference_ids} />
    <details className="reviewed-method"><summary>Where these examples come from</summary><p>These are selected records from the existing 500,000-product catalog. Photos and quoted specifications are preserved. The summaries are reviewed reading aids and never change search scores. This page compares evidence; it does not simulate a search result.</p>
      {example.products.filter(product => product.source_label).map(product => <p key={product.product_id}><strong>{product.display_name}:</strong> ESCI query “{product.source_label?.query}” assigned {product.source_label?.label} ({product.source_label?.split} split). {product.source_label?.title_unchanged ? 'The titles match across snapshots.' : 'The current title differs from the older snapshot.'} The label describes that reference query; it does not prove every requirement here.</p>)}
      <p>ESCI: E = Exact, S = Substitute, C = Complement, I = Irrelevant. Reviewed test examples are discovery material, not an untouched test set.</p>
      <p>WANDS records retain their own product IDs and labels. Amazon products never inherit a WANDS label. Both sources are small, reviewed selections here; these comparisons do not establish whole-catalog accuracy.</p>
      <p><a href={reviewedExamples.sources.esci} target="_blank" rel="noreferrer">Amazon ESCI</a> · <a href={reviewedExamples.sources.wands} target="_blank" rel="noreferrer">Wayfair WANDS</a></p>
    </details>
  </div>;
}
