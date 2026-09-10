import { ArrowRight } from "lucide-react";
import { Link } from "wouter";
import { ResultProductCard } from "./ResultProductCard";
import { KeepInMind } from "./KeepInMind";
import { productImageMap } from "../media";
import type { ProductSummary, ScorecardStageAblation, ScorecardStageArmKey, SearchResponse } from "../types";

const rank = (value: number | null | undefined) => value == null ? "—" : `#${value}`;
// Select once by final position so both columns follow the same products.
const previewProducts = (response?: SearchResponse) => response?.results.slice(0, 3) ?? [];

/** The column's own words for each measured arm, so the table reads like the counts above it. */
const armTitle: Record<ScorecardStageArmKey, string> = {
  lexical_only: "Keyword alone",
  trigram_only: "Close spelling alone",
  semantic_only: "Meaning alone",
  rrf_fused_no_rerank: "All three combined",
  rrf_fused_reranked: "Combined, then reranked",
};
const singleArms = new Set<ScorecardStageArmKey>(["lexical_only", "trigram_only", "semantic_only"]);
const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;

/** How many of the three arms fetched this product: null ranks are arms that never saw it. */
export function armsThatFound(product: ProductSummary): number {
  const signals = product.signals;
  if (!signals) return 0;
  return [signals.fts.rank, signals.trigram.rank, signals.semantic.rank].filter((value) => value != null).length;
}

/**
 * What combining and reranking each added, derived from the measured arms
 * rather than typed: the gap between the fused arm and the best single arm,
 * then the reranking step's own paired verdict.
 */
export function stageGainSentence(ablation: ScorecardStageAblation): string | null {
  const arms = new Map(ablation.arms.map((arm) => [arm.key, arm]));
  const fused = arms.get("rrf_fused_no_rerank");
  const reranked = arms.get("rrf_fused_reranked");
  const bestSingle = ablation.arms.filter((arm) => singleArms.has(arm.key)).sort((a, b) => b.ndcg_at_10 - a.ndcg_at_10)[0];
  if (!fused || !reranked || !bestSingle) return null;
  const rerankStep = ablation.paired_comparisons.find((step) => step.to_key === "rrf_fused_reranked");
  const rerank = `reranking ${rerankStep?.separable ? "adds" : "moves it"} ${signed(reranked.ndcg_at_10 - fused.ndcg_at_10)}${rerankStep && !rerankStep.separable ? ", inside the spread of these searches" : ""}`;
  return `Combining adds ${signed(fused.ndcg_at_10 - bestSingle.ndcg_at_10)} nDCG@10 over ${armTitle[bestSingle.key]}; ${rerank}.`;
}

function ProductPreview({ products, ranked = false }: { products: ProductSummary[]; ranked?: boolean }) {
  const images = productImageMap(products);
  return <ul className="inspector-product-preview" aria-label={ranked ? "Final ranking preview" : "Retrieved product preview"}>
    {products.map((product) => <li key={product.product_id}>
      <ResultProductCard product={product} imageSrc={images.get(product.product_id)} footer={ranked ? <><span>Before → final</span><span className="inspector-preview-ranks" aria-label={`${rank(product.signals?.pre_rerank_rank)} before rerank, ${rank(product.signals?.final_rank)} in the final order`}>{rank(product.signals?.pre_rerank_rank)} <ArrowRight size={14} aria-hidden="true" /> <strong>{rank(product.signals?.final_rank)}</strong></span></> : <span>Before reranking · {rank(product.signals?.pre_rerank_rank)}</span>} />
    </li>)}
  </ul>;
}

/** The measured answer to "why hybrid": each arm alone, then combined, then reranked. */
function WithoutHybrid({ response, ablation }: { response?: SearchResponse; ablation: ScorecardStageAblation | null | undefined }) {
  const returned = response?.results ?? [];
  const oneArmOnly = returned.filter((product) => armsThatFound(product) === 1).length;
  const gain = ablation?.attributed ? stageGainSentence(ablation) : null;
  return <section className="inspector-without-hybrid" aria-labelledby="inspector-without-hybrid-title">
    <h3 id="inspector-without-hybrid-title" className="inspector-preview-title">Without hybrid</h3>
    {returned.length ? <p className="inspector-note">In this run, {oneArmOnly} of the {returned.length} products returned came from one arm only. A single arm would have missed {oneArmOnly === 1 ? "it" : "them"}.</p> : null}
    {ablation?.attributed ? <>
      <table className="inspector-arm-table" aria-label="What each arm alone scores">
        <thead><tr><th scope="col">Arm</th><th scope="col">nDCG@10</th><th scope="col">Recall@10</th><th scope="col">MRR</th></tr></thead>
        <tbody>{ablation.arms.map((arm) => <tr key={arm.key} data-served={arm.key === "rrf_fused_reranked" || undefined}>
          <th scope="row">{armTitle[arm.key]}</th><td>{arm.ndcg_at_10.toFixed(2)}</td><td>{arm.recall_at_10.toFixed(2)}</td><td>{arm.mrr.toFixed(2)}</td>
        </tr>)}</tbody>
        <caption>Measured on {ablation.scored_query_count} graded searches against this catalog. <Link href="/labs/retrieval?view=lab#labs-stage-prove">Prove shows each step’s spread.</Link></caption>
      </table>
      {gain ? <p className="inspector-note">{gain}</p> : null}
    </> : <p className="inspector-note">{ablation ? "The measured comparison is waiting for a re-measure on this build." : "Loading the measured comparison…"}</p>}
  </section>;
}

export function RetrieveOverview({ response, ablation }: { response?: SearchResponse; ablation?: ScorecardStageAblation | null }) {
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
    <WithoutHybrid response={response} ablation={ablation} />
    {response ? products.length ? <>
      <h3 className="inspector-preview-title">The same matches, before reranking</h3>
      <ProductPreview products={products} />
      <p className="inspector-note">Following the same {products.length} products as Rank, in their earlier order. This is a preview of the returned results.</p>
    </> : <p className="inspector-waiting">This search returned no products.</p> : <p className="inspector-waiting">Matching products will appear as the search finishes.</p>}
    <KeepInMind>Recall is decided here. A reranker can only reorder what entered this pool, and every filter was applied inside each arm before any limit.</KeepInMind>
  </>;
}

export function RankOverview({ response, ablation }: { response?: SearchResponse; ablation?: ScorecardStageAblation | null }) {
  const products = previewProducts(response);
  const rerankStep = ablation?.attributed ? ablation.paired_comparisons.find((step) => step.to_key === "rrf_fused_reranked") : undefined;
  return <>
    <div className="inspector-rank-flow"><span>RRF fusion</span><ArrowRight size={14} aria-hidden="true" /><span>Cohere Rerank</span></div>
    <p className="inspector-note">Combine the search results, then check how well each product fits Alex’s request.</p>
    {rerankStep ? <p className="inspector-note">Measured on {ablation?.scored_query_count} graded searches: combining the arms is the large step; reranking moved the ordering score by {signed(rerankStep.mean_difference)} on average, {rerankStep.separable ? "more than" : "inside"} the spread of the per-search differences.</p> : null}
    {response ? products.length ? <>
      <div className="inspector-preview-heading"><h3 className="inspector-preview-title">Top matches</h3><span>RRF rank → final rank</span></div>
      <ProductPreview products={products} ranked />
      <p className="inspector-note">#1 is the highest rank. RRF and reranker scores use different scales; a higher score is better within each step.</p>
      <p className="inspector-note">Showing {products.length} of {response.results.length} results. Reranking: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>.</p>
    </> : <p className="inspector-waiting">No products were returned, so no ranking is available.</p> : <p className="inspector-waiting">See how the order changes as Mosaic compares the products.</p>}
    <KeepInMind>Fusion adds rank positions, never raw scores, because the three arms do not share a scale. The reranker reorders the pool it is handed; it cannot add a product to it.</KeepInMind>
  </>;
}
