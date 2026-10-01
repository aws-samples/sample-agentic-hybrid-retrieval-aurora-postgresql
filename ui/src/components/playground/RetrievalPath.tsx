import { Link } from "wouter";
import { armLanguage } from "../../retrievalLanguage";
import type { ProductSummary, ScorecardStageAblation, ScorecardStageArmKey, SearchResponse } from "../../types";

/** The measured arms in the words the method rows use. */
const armTitle: Record<ScorecardStageArmKey, string> = {
  lexical_only: "Keyword alone",
  trigram_only: "Close spelling alone",
  semantic_only: "Meaning alone",
  rrf_fused_no_rerank: "All three combined",
  rrf_fused_reranked: "Combined, then reranked",
};
const singleArms = new Set<ScorecardStageArmKey>(["lexical_only", "trigram_only", "semantic_only"]);
/** A measured difference with its sign, as the scorecard prints it. */
export const signedScore = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
const COUNT_KEY = { fts: "fts_in_pool", trigram: "trigram_in_pool", semantic: "semantic_in_pool" } as const;
const LIMIT_KEY = { fts: "fts_limit", trigram: "trigram_limit", semantic: "semantic_limit" } as const;
const TECH = { fts: "tsvector · GIN", trigram: "pg_trgm · GIN", semantic: "pgvector · HNSW" } as const;
const TIMINGS: [string, string][] = [
  ["embedding", "Embedding"],
  ["postgresql_retrieval", "PostgreSQL retrieval"],
  ["rerank", "Rerank"],
];

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
  const inside = (fromKey: ScorecardStageArmKey, toKey: ScorecardStageArmKey) => {
    const step = ablation.paired_comparisons.find((item) => item.from_key === fromKey && item.to_key === toKey);
    return step && !step.separable ? " (inside the spread of these searches)" : "";
  };
  const combining = `Combining changes the ordering score (nDCG@10) by ${signedScore(fused.ndcg_at_10 - bestSingle.ndcg_at_10)} compared with ${armTitle[bestSingle.key]}${inside(bestSingle.key, "rrf_fused_no_rerank")}`;
  const rerank = `reranking moves it ${signedScore(reranked.ndcg_at_10 - fused.ndcg_at_10)}${inside("rrf_fused_no_rerank", "rrf_fused_reranked")}`;
  return `${combining}; ${rerank}.`;
}

/** The measured reranking step, for the Rank section's own sentence. */
export function rerankStep(ablation: ScorecardStageAblation | null | undefined) {
  return ablation?.attributed ? ablation.paired_comparisons.find((step) => step.to_key === "rrf_fused_reranked") : undefined;
}


/** "Cohere Embed v4" from "us.cohere.embed-v4:0"; any other id as recorded. */
export function modelName(modelId: string | null | undefined): string | null {
  if (!modelId) return null;
  const cohere = /cohere\.(embed|rerank)-v?([\d-]+)/i.exec(modelId);
  if (!cohere) return modelId;
  const version = cohere[2].replace(/-/g, ".");
  return `Cohere ${cohere[1] === "embed" ? "Embed" : "Rerank"} v${version}`;
}

const seconds = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);

/**
 * The run as five steps: what exists, what the filters admit, what each method
 * found, what fusion kept, and what reranking returned. Every figure is the
 * selected search's own record; a step the record lacks shows a dash.
 */
export function RetrievalPath({ response, catalogCount, eligible }: {
  response?: SearchResponse;
  catalogCount?: number;
  eligible: string;
}) {
  const diagnostics = response?.diagnostics;
  const counts = diagnostics?.candidate_counts;
  const profile = diagnostics?.retrieval_profile;
  const timings = diagnostics?.stage_timings_ms ?? {};
  return <>
    <ol className="pg-flow" aria-label="From catalog to final order">
      <li><h3>Catalog</h3><p className="pg-flow-n">{catalogCount ? catalogCount.toLocaleString() : "—"}</p><small>Source listings with saved embeddings</small></li>
      <li><h3>Eligible</h3><p className="pg-flow-n">{eligible}</p><small>Filters checked in PostgreSQL before any limit</small></li>
      <li className="pg-flow-arms"><h3>In the combined pool</h3>
        <dl aria-label="Candidates surviving fusion from each search">
          {armLanguage.map((arm) => {
            const count = counts?.[COUNT_KEY[arm.key]];
            return <div key={arm.key} data-arm={arm.key} data-empty={count === 0 || undefined}>
              <dt><i aria-hidden="true" />{arm.label}</dt>
              <dd>{count ?? "—"}</dd>
              <small>{TECH[arm.key]}{profile ? ` · top ${profile[LIMIT_KEY[arm.key]]}` : ""}</small>
            </div>;
          })}
        </dl>
      </li>
      <li><h3>Combined</h3><p className="pg-flow-n">{counts?.fused_pool ?? "—"}</p><small>{profile ? `Reciprocal rank fusion, k = ${profile.rrf_k}` : "Reciprocal rank fusion"}</small></li>
      <li><h3>Re-rank</h3><p className="pg-flow-n">{diagnostics?.rerank_status === "applied" ? counts?.fused_pool ?? "—" : diagnostics?.rerank_status ?? "—"}</p><small>{modelName(diagnostics?.rerank_model_id) ?? "Reranker not recorded"}{response ? ` · ${response.results.length} displayed` : ""}</small></li>
    </ol>
    {diagnostics ? <p className="pg-timings">
      {TIMINGS.filter(([key]) => typeof timings[key] === "number").map(([key, label]) => <span key={key}><b>{label}</b> {seconds(timings[key])}</span>)}
      <span><b>Total</b> {seconds(diagnostics.total_latency_ms)}</span>
    </p> : <p className="pg-timings">{response ? "This saved search carries no timing record." : "Counts describe candidates surviving fusion, not each search’s full list. They can overlap."}</p>}
  </>;
}

/** The measured answer to "why hybrid": each arm alone, then combined, then reranked. */
export function MethodComparison({ response, ablation }: { response?: SearchResponse; ablation: ScorecardStageAblation | null | undefined }) {
  const returned = response?.results ?? [];
  const oneArmOnly = returned.filter((product) => armsThatFound(product) === 1).length;
  const gain = ablation?.attributed ? stageGainSentence(ablation) : null;
  return <section className="pg-methods" aria-labelledby="pg-methods-title">
    <h3 id="pg-methods-title">Why use more than one search method?</h3>
    {returned.length ? <p>In this run, {oneArmOnly} of the {returned.length} products returned were found by only one search method. Those products depend on the method that found them.</p> : null}
    <details className="pg-disclosure"><summary>Compare search methods</summary><div>
      <p>Compare word search, meaning search, the combined list, then reranking. Keep the request, filters and settings fixed. Check which suitable products were found, where they appear, and the extra time and model usage.</p>
      <p>Include requests that already work well. A hybrid search is not automatically better; keep unchanged results and regressions in the comparison.</p>
      {ablation?.attributed ? <>
        <table className="pg-arm-table" aria-label="Scores for each search method">
          <thead><tr><th scope="col">Method</th><th scope="col">Ordering <small>nDCG@10</small></th><th scope="col">Found <small>Recall@10</small></th><th scope="col">First match <small>MRR</small></th></tr></thead>
          <tbody>{ablation.arms.map((arm) => <tr key={arm.key} data-served={arm.key === "rrf_fused_reranked" || undefined}>
            <th scope="row">{armTitle[arm.key]}</th><td>{arm.ndcg_at_10.toFixed(2)}</td><td>{arm.recall_at_10.toFixed(2)}</td><td>{arm.mrr.toFixed(2)}</td>
          </tr>)}</tbody>
          <caption>Measured on {ablation.scored_query_count} graded searches against this catalog. <Link href="/labs/retrieval?view=lab#labs-stage-prove">Open Prove for score definitions and results for each search.</Link></caption>
        </table>
        {gain ? <p>{gain}</p> : null}
      </> : <p>{ablation ? "The measured comparison is waiting for a re-measure on this build." : "Loading the measured comparison…"}</p>}
    </div></details>
  </section>;
}
