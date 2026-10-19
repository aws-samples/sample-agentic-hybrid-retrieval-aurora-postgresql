import { armLanguage } from "../../retrievalLanguage";
import type { ProductSummary, SearchResponse } from "../../types";
import { pickName } from "../ask-mosaic/comparison";

const ROWS = 5;

/**
 * Aurora's combined order for its first products, each bar built from the share
 * every search gave it: 1 / (k + that search's rank). A product one search
 * missed simply has no segment from it, which is the whole of RRF in a row.
 */
export function FusionRows({ response, followId }: { response: SearchResponse; followId: number | null }) {
  const ranked = response.results
    .filter((product): product is ProductSummary & { signals: NonNullable<ProductSummary["signals"]> } => Boolean(product.signals))
    .sort((a, b) => a.signals.pre_rerank_rank - b.signals.pre_rerank_rank);
  const rows = ranked.slice(0, ROWS);
  const followed = ranked.find((product) => product.product_id === followId);
  if (followed && !rows.includes(followed)) rows.push(followed);
  const best = Math.max(0, ...rows.map((product) => product.signals.rrf_score));
  if (!rows.length || best <= 0) return null;
  return <div className="pg-fusion">
    <p className="pg-fusion-key" aria-hidden="true">
      {armLanguage.map((arm) => <span key={arm.key} data-arm={arm.key}><i />{arm.label}</span>)}
    </p>
    <ol aria-label="Each product's share from each search">
      {rows.map((product) => {
        const signals = product.signals;
        const parts = armLanguage.filter((arm) => signals[arm.key].rrf_contribution);
        return <li key={product.product_id} data-followed={product.product_id === followId || undefined}>
          <span className="pg-fusion-rank">#{signals.pre_rerank_rank}</span>
          <span className="pg-fusion-name">{pickName(product)}</span>
          <span className="pg-fusion-bar" role="img" aria-label={parts.map((arm) => `${arm.label} #${signals[arm.key].rank}`).join(", ") || "No search share"}>
            {parts.map((arm) => <i key={arm.key} data-arm={arm.key} title={`${arm.label} #${signals[arm.key].rank}: 1 / (k + ${signals[arm.key].rank})`} style={{ width: `${((signals[arm.key].rrf_contribution ?? 0) / best) * 100}%` }} />)}
          </span>
          <span className="pg-fusion-total">{signals.rrf_score.toFixed(4)}</span>
        </li>;
      })}
    </ol>
  </div>;
}
