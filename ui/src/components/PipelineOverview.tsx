import { ArrowRight } from "lucide-react";
import { ResultProductCard } from "./ResultProductCard";
import { KeepInMind } from "./KeepInMind";
import { productImageMap } from "../media";
import type { ProductSummary, SearchResponse } from "../types";

const rank = (value: number | null | undefined) => value == null ? "—" : `#${value}`;
// Select once by final position so both columns follow the same products.
const previewProducts = (response?: SearchResponse) => response?.results.slice(0, 3) ?? [];

function ProductPreview({ products, ranked = false }: { products: ProductSummary[]; ranked?: boolean }) {
  const images = productImageMap(products);
  return <ul className="inspector-product-preview" aria-label={ranked ? "Final ranking preview" : "Retrieved product preview"}>
    {products.map((product) => <li key={product.product_id}>
      <ResultProductCard product={product} imageSrc={images.get(product.product_id)} footer={ranked ? <><span>Before → final</span><span className="inspector-preview-ranks" aria-label={`${rank(product.signals?.pre_rerank_rank)} before rerank, ${rank(product.signals?.final_rank)} in the final order`}>{rank(product.signals?.pre_rerank_rank)} <ArrowRight size={14} aria-hidden="true" /> <strong>{rank(product.signals?.final_rank)}</strong></span></> : <span>Before reranking · {rank(product.signals?.pre_rerank_rank)}</span>} />
    </li>)}
  </ul>;
}

export function RetrieveOverview({ response }: { response?: SearchResponse }) {
  const counts = response?.diagnostics?.candidate_counts;
  // These are the recorded returned products, not an invented view of the whole pool.
  const products = previewProducts(response).sort((a, b) => (a.signals?.pre_rerank_rank ?? Infinity) - (b.signals?.pre_rerank_rank ?? Infinity));
  return <>
    <dl className="inspector-arm-counts" aria-label="Matches found by each search">
      <div><dt>Keyword <small>tsvector · GIN</small></dt><dd>{counts?.fts_in_pool ?? "—"}</dd></div>
      <div><dt>Close spelling <small>pg_trgm · GIN</small></dt><dd>{counts?.trigram_in_pool ?? "—"}</dd></div>
      <div><dt>Meaning <small>Cohere Embed · pgvector</small></dt><dd>{counts?.semantic_in_pool ?? "—"}</dd></div>
    </dl>
    <p className="inspector-note">A product can match in more than one way.</p>
    {response ? products.length ? <>
      <h3 className="inspector-preview-title">The same matches, before reranking</h3>
      <ProductPreview products={products} />
      <p className="inspector-note">Following the same {products.length} products as Rank, in their earlier order. This is a preview of the returned results.</p>
    </> : <p className="inspector-waiting">This search returned no products.</p> : <p className="inspector-waiting">Matching products will appear as the search finishes.</p>}
    <KeepInMind>Recall is decided here. A reranker can only reorder what entered this pool, and every filter was applied inside each arm before any limit.</KeepInMind>
  </>;
}

export function RankOverview({ response }: { response?: SearchResponse }) {
  const products = previewProducts(response);
  return <>
    <div className="inspector-rank-flow"><span>RRF fusion</span><ArrowRight size={14} aria-hidden="true" /><span>Cohere Rerank</span></div>
    <p className="inspector-note">Combine the search results, then check how well each product fits Alex’s request.</p>
    {response ? products.length ? <>
      <div className="inspector-preview-heading"><h3 className="inspector-preview-title">Top matches</h3><span>RRF rank → final rank</span></div>
      <ProductPreview products={products} ranked />
      <p className="inspector-note">#1 is the highest rank. RRF and reranker scores use different scales; a higher score is better within each step.</p>
      <p className="inspector-note">Showing {products.length} of {response.results.length} results. Reranking: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>.</p>
    </> : <p className="inspector-waiting">No products were returned, so no ranking is available.</p> : <p className="inspector-waiting">See how the order changes as Mosaic compares the products.</p>}
    <KeepInMind>Fusion adds rank positions, never raw scores, because the three arms do not share a scale. The reranker reorders the pool it is handed; it cannot add a product to it.</KeepInMind>
  </>;
}
