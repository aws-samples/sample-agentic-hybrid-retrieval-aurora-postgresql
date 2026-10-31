import type { CSSProperties } from "react";
import { specFacts } from "../format";
import { isWeightedFusion } from "../fusion";
import { FINAL_LABEL, FUSED_LABEL, armLanguage } from "../retrievalLanguage";
import type { RetrievalArm } from "../retrievalLanguage";
import type { ProductSummary, RetrievalDiagnostics } from "../types";

/**
 * "Cohere Rerank relevance score" only when the recorded model id says so;
 * otherwise the generic "relevance score". The receipt never guesses a
 * version number a model id does not spell out.
 */
function rerankRelevanceLabel(modelId: string | null | undefined): string {
  return modelId && /cohere/i.test(modelId)
    ? "Cohere Rerank relevance score"
    : "relevance score";
}

const ARM_WEIGHT: Record<RetrievalArm, "weight_fts" | "weight_fuzzy" | "weight_semantic"> = {
  fts: "weight_fts",
  fuzzy: "weight_fuzzy",
  semantic: "weight_semantic",
};

/**
 * "1 ÷ (60 + 130) = 0.0053": what this position contributes by the formula,
 * printed beside the contribution the search recorded. They agree when fusion
 * is right; Lab 2's fault is the one place they do not. A weighted run (a
 * maintainer mode) multiplies by the arm's weight, so its formula says so.
 */
function rrfFormula(
  arm: RetrievalArm,
  rank: number,
  diagnostics: RetrievalDiagnostics,
): string {
  const profile = diagnostics.retrieval_profile;
  const weight = isWeightedFusion(diagnostics.strategy) ? profile[ARM_WEIGHT[arm]] : 1;
  const share = weight / (profile.rrf_k + rank);
  return `${weight} ÷ (${profile.rrf_k} + ${rank}) = ${share.toFixed(4)}`;
}

/**
 * One product's itemized receipt from the search that returned it, in the
 * shopper vocabulary: each method that found it with its position and what that
 * position contributed, the combined total before reranking, the reranker's
 * score, the final position, and what the listing itself states. Every value is
 * recorded by the saved search. A method that did not find the product says
 * "no match" with no position, because a position there would be one Mosaic
 * invented; that absence is what Lab 1 asks a participant to notice.
 *
 * `diagnostics` supplies the arithmetic's k and the reranking pool size, read
 * from the same search response rather than a literal: `scripts/checks/config_tripwire.py`
 * fails the build on a second copy of `rrf_k` or the candidate pool size. When a
 * response carries no diagnostics (a replay, or a call that asked for none), the
 * sub-lines that need them are omitted rather than invented; the base position
 * and contribution figures still render from the signals alone.
 */
export function ProductReceiptBody({
  product,
  diagnostics,
}: {
  product: ProductSummary;
  diagnostics?: RetrievalDiagnostics | null;
}) {
  const signals = product.signals;
  if (!signals) return null;
  const facts = specFacts(product.specs, 4);
  const fusedPool = diagnostics?.candidate_counts.fused_pool;
  let line = 0;
  const settle = () => ({ "--line": line++ }) as CSSProperties;
  return (
    <div className="product-receipt-card">
      <ol>
        {armLanguage.map((arm) => {
          const signal = signals[arm.key];
          const rank = signal?.rank || null;
          const found = rank !== null;
          return (
            <li key={arm.key} className={found ? "retrieve" : "retrieve missed"} style={settle()}>
              <span className="receipt-what"><i aria-hidden="true" />{arm.label}</span>
              <span className="receipt-rank">{found ? `#${rank}` : ""}</span>
              <span className="receipt-value">{found ? (signal.rrf_contribution?.toFixed(4) ?? "") : "no match"}</span>
              {found ? (
                diagnostics ? (
                  <span className="receipt-how">{`position ${rank} · ${rrfFormula(arm.key, rank, diagnostics)}`}</span>
                ) : null
              ) : (
                <span className="receipt-how">no match for this request</span>
              )}
            </li>
          );
        })}
        <li className="rank subtotal" style={settle()}>
          <span className="receipt-what"><i aria-hidden="true" />{FUSED_LABEL}</span>
          <span className="receipt-rank">#{signals.pre_rerank_rank}</span>
          <span className="receipt-value">{signals.rrf_score.toFixed(4)}</span>
          {typeof fusedPool === "number" && fusedPool > 0 ? (
            <>
              <span className="receipt-pool-bar" aria-hidden="true">
                <i
                  style={{
                    left: `${Math.min(100, Math.max(0, (signals.pre_rerank_rank / fusedPool) * 100))}%`,
                  }}
                />
              </span>
              <span className="receipt-how">{`position ${signals.pre_rerank_rank} on the shortlist of ${fusedPool}, before reranking`}</span>
            </>
          ) : null}
        </li>
        {signals.rerank_score != null ? (
          <li className="rank" style={settle()}>
            <span className="receipt-what"><i aria-hidden="true" />Reranked</span>
            <span className="receipt-rank" />
            <span className="receipt-value">{signals.rerank_score.toFixed(3)}</span>
            <span className="receipt-how">{rerankRelevanceLabel(diagnostics?.rerank_model_id)}</span>
          </li>
        ) : null}
        <li className="total" style={settle()}>
          <span className="receipt-what">{FINAL_LABEL}</span>
          <span className="receipt-rank">#{signals.final_rank}</span>
          <span className="receipt-value" />
        </li>
      </ol>
      {facts.length ? (
        <section className="receipt-states" aria-label="What the listing states" style={settle()}>
          <h4>What the listing states</h4>
          <dl>
            {facts.map((fact) => (
              <div key={fact.key}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}<q title={fact.quote}>{fact.quote}</q></dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  );
}
