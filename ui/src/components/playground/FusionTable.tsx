import { useState } from "react";
import { productImage } from "../../media";
import { armLanguage } from "../../retrievalLanguage";
import type { ProductSummary, SearchResponse } from "../../types";
import { pickName } from "../ask-mosaic/comparison";

const ROWS = 5;

type Ranked = ProductSummary & { signals: NonNullable<ProductSummary["signals"]> };

/**
 * How each product reached its combined position, as arithmetic: every search's
 * `1 / (k + rank)` beside the share the database reported for it, their sum, and
 * the `rrf_score` the run reported. The operands are printed, not only the result,
 * because a share that ignores the rank looks fine as a score and wrong beside the
 * rank it should have used. `k` comes from the run's own profile, never a default.
 */
export function FusionTable({ response, followId, images }: {
  response: SearchResponse;
  followId: number | null;
  images: Map<number, string>;
}) {
  const [all, setAll] = useState(false);
  const k = response.diagnostics?.retrieval_profile?.rrf_k;
  const ranked = response.results
    .filter((product): product is Ranked => Boolean(product.signals))
    .sort((a, b) => a.signals.pre_rerank_rank - b.signals.pre_rerank_rank);
  if (k == null || !ranked.length) return null;
  const rows = all ? ranked : ranked.slice(0, ROWS);
  const followed = ranked.find((product) => product.product_id === followId);
  if (followed && !rows.includes(followed)) rows.push(followed);
  return <div className="pg-fusion">
    <p className="pg-fusion-formula">
      Each search adds <code>1 / (k + its rank)</code>, with <code>k = {k}</code> for this run.
      Aurora orders the pool by the sum.
    </p>
    <div className="pg-fusion-scroll" role="region" tabIndex={0} aria-label="How each product reached its combined position">
      <table className="pg-fusion-table">
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Combined position</span></th>
            <th scope="col">Product</th>
            {armLanguage.map((arm) => <th scope="col" key={arm.key} data-arm={arm.key}>{arm.label}</th>)}
            <th scope="col">Sum</th>
            <th scope="col">Reported <code>rrf_score</code></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((product) => {
            const signals = product.signals;
            const sum = armLanguage.reduce((total, arm) => total + (signals[arm.key].rrf_contribution ?? 0), 0);
            // The tolerance labOutcome uses: a sum that disagrees with the reported
            // score is a fusion defect, not rounding.
            const agrees = Math.abs(sum - signals.rrf_score) <= 1e-9;
            return <tr key={product.product_id} data-followed={product.product_id === followId || undefined}>
              <td className="pg-fusion-rank">#{signals.pre_rerank_rank}</td>
              <th scope="row">
                <span className="pg-fusion-product">
                  <img src={images.get(product.product_id) ?? productImage(product)} alt="" width={32} height={32} loading="lazy" decoding="async" />
                  <span>{pickName(product)}</span>
                </span>
              </th>
              {armLanguage.map((arm) => {
                const part = signals[arm.key];
                return <td key={arm.key} data-arm={arm.key}>
                  {part.rank == null ? <span className="pg-fusion-miss">not found</span> : <>
                    <code>1 / ({k} + {part.rank})</code>
                    <b>{part.rrf_contribution?.toFixed(4) ?? "–"}</b>
                  </>}
                </td>;
              })}
              <td className="pg-fusion-sum">{sum.toFixed(4)}</td>
              <td className="pg-fusion-reported" data-agrees={agrees || undefined}>
                {signals.rrf_score.toFixed(4)}
                {agrees ? null : <small>does not match the sum</small>}
              </td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
    {ranked.length > ROWS ? <button type="button" className="pg-fusion-more" onClick={() => setAll(!all)}>
      {all ? `Show the first ${ROWS}` : `Show all ${ranked.length}`}
    </button> : null}
  </div>;
}
