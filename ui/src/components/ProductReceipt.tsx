import type { CSSProperties } from "react";
import { specFacts } from "../format";
import { FINAL_LABEL, FUSED_LABEL, armLanguage } from "../retrievalLanguage";
import type { ProductSummary } from "../types";

/**
 * One product's itemized receipt from the search that returned it, in the
 * shopper vocabulary: each method that found it with its position and what that
 * position contributed, the combined total before reranking, the reranker's
 * score, the final position, and what the listing itself states. Every value is
 * recorded by the saved search. A method that did not find the product says
 * "no match" with no position, because a position there would be one Mosaic
 * invented; that absence is what Lab 1 asks a participant to notice.
 */
export function ProductReceiptBody({ product }: { product: ProductSummary }) {
  const signals = product.signals;
  if (!signals) return null;
  const facts = specFacts(product.specs, 4);
  let line = 0;
  const settle = () => ({ "--line": line++ }) as CSSProperties;
  return (
    <div className="product-receipt-card">
      <ol>
        {armLanguage.map((arm) => {
          const signal = signals[arm.key];
          const found = Boolean(signal?.rank);
          return (
            <li key={arm.key} className={found ? "retrieve" : "retrieve missed"} style={settle()}>
              <span className="receipt-what"><i aria-hidden="true" />{arm.label}</span>
              <span className="receipt-rank">{found ? `#${signal.rank}` : ""}</span>
              <span className="receipt-value">{found ? (signal.rrf_contribution?.toFixed(4) ?? "") : "no match"}</span>
            </li>
          );
        })}
        <li className="rank subtotal" style={settle()}>
          <span className="receipt-what"><i aria-hidden="true" />{FUSED_LABEL}</span>
          <span className="receipt-rank">#{signals.pre_rerank_rank}</span>
          <span className="receipt-value">{signals.rrf_score.toFixed(4)}</span>
        </li>
        {signals.rerank_score != null ? (
          <li className="rank" style={settle()}>
            <span className="receipt-what"><i aria-hidden="true" />Reranked</span>
            <span className="receipt-rank" />
            <span className="receipt-value">{signals.rerank_score.toFixed(3)}</span>
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
