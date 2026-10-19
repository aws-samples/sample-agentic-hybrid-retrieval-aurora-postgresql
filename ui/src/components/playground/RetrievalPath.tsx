import { Link } from "wouter";
import type { ScorecardStageAblation, ScorecardStageArmKey, SearchResponse } from "../../types";

/** The measured arms in the words the method rows use. */
const armTitle: Record<ScorecardStageArmKey, string> = {
  lexical_only: "Full-text search alone",
  trigram_only: "Fuzzy matching alone",
  semantic_only: "Semantic search alone",
  rrf_fused_no_rerank: "All three combined",
  rrf_fused_reranked: "Combined, then reranked",
};
const singleArms = new Set<ScorecardStageArmKey>(["lexical_only", "trigram_only", "semantic_only"]);
/** A measured difference with its sign, as the scorecard prints it. */
export const signedScore = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;

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

/** The measured answer to "why hybrid": each method alone, then combined, then reranked. */
export function MethodComparison({ ablation }: { response?: SearchResponse; ablation: ScorecardStageAblation | null | undefined }) {
  const gain = ablation?.attributed ? stageGainSentence(ablation) : null;
  return <details className="pg-disclosure pg-methods"><summary>Compare search methods</summary><div>
    {ablation?.attributed ? <>
      <table className="pg-arm-table" aria-label="Scores for each search method">
        <thead><tr><th scope="col">Method</th><th scope="col">Ordering <small>nDCG@10</small></th><th scope="col">Found <small>Recall@10</small></th><th scope="col">First match <small>MRR</small></th></tr></thead>
        <tbody>{ablation.arms.map((arm) => <tr key={arm.key} data-served={arm.key === "rrf_fused_reranked" || undefined}>
          <th scope="row">{armTitle[arm.key]}</th><td>{arm.ndcg_at_10.toFixed(2)}</td><td>{arm.recall_at_10.toFixed(2)}</td><td>{arm.mrr.toFixed(2)}</td>
        </tr>)}</tbody>
        <caption>Measured on {ablation.scored_query_count} judged searches against this catalog. <Link href="/labs/retrieval?view=lab#labs-stage-prove">Open Prove for score definitions and results for each search.</Link></caption>
      </table>
      {gain ? <p>{gain}</p> : null}
    </> : <p>{ablation ? "The measured comparison is waiting for a re-measure on this build." : "Loading the measured comparison…"}</p>}
  </div></details>;
}
