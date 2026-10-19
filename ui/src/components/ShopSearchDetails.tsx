import { useState } from "react";
import { Link } from "wouter";
import type { WantedProduct } from "../labOutcome";
import { playgroundQueryHref } from "../navigation";
import { armLanguage } from "../retrievalLanguage";
import type { SearchResponse } from "../types";
import { WantedBadge } from "./ProductCard";
import "../shop-search-details.css";

/** ▲n / ▼n in tabular numerals, spoken as "up n". Held products read "Held". */
function Movement({ moved }: { moved: number | null }) {
  if (moved === null) return <>—</>;
  if (moved === 0) return <>Held</>;
  const up = moved > 0;
  return <span className="shop-details-move">
    <span aria-hidden="true">{up ? "▲" : "▼"}{Math.abs(moved)}</span>
    <span className="sr-only">{up ? "up" : "down"} {Math.abs(moved)}</span>
  </span>;
}

export function ShopSearchDetails({
  response, onSelect, onHighlight, highlightedId, wanted = null, wantedName = null,
}: {
  response: SearchResponse;
  onSelect: (id: number) => void;
  onHighlight: (id: number | null) => void;
  highlightedId: number | null;
  /** The active lab's wanted product, read from this response. */
  wanted?: WantedProduct | null;
  wantedName?: string | null;
}) {
  const [order, setOrder] = useState<"combined" | "final">("final");
  const products = [...response.results].sort((a, b) => {
    const rank = (product: typeof a) => (order === "combined"
      ? product.signals?.pre_rerank_rank : product.signals?.final_rank) ?? Infinity;
    return rank(a) - rank(b);
  });
  const pool = response.diagnostics?.candidate_counts.fused_pool;
  const reranked = response.diagnostics?.rerank_status === "applied";

  return <aside className="shop-search-details" aria-label="Search details for these products">
    <header>
      <h2>How the order changed</h2>
      <p>Full-text search, fuzzy matching and semantic search each rank products. Their positions are combined, then the reranker compares the shortlist with your full request.</p>
    </header>
    {!reranked ? <p>This request was not reranked. Final positions may reflect the combined order or an exact listing match.</p> : null}
    {wanted?.tier === "missing" ? <p className="shop-details-wanted">
      <WantedBadge wanted={wanted} />
      {wantedName ? <span>{wantedName}</span> : null}
    </p> : null}
    <p id="shop-sort-label" className="shop-sort-label">Sort these displayed products by:</p>
    <div className="shop-details-order pg-seg" role="group" aria-labelledby="shop-sort-label">
      <button type="button" aria-pressed={order === "combined"} onClick={() => setOrder("combined")}>Before reranking (RRF)</button>
      <button type="button" aria-pressed={order === "final"} onClick={() => setOrder("final")}>Final position</button>
    </div>
    <p className="shop-details-scope">Same {products.length} displayed products{pool == null ? "" : ` from ${pool} ${reranked ? "sent to reranking" : "in the combined list"}`} in both views; only the row order changes. Gaps in positions belong to other products in that list.</p>
    <div className="shop-details-table" tabIndex={0} role="region" aria-label="Product positions before and after reranking">
      <table>
        <caption>Positions from this saved search. ▲ moved closer to first, ▼ moved further away.</caption>
        <thead><tr><th scope="col">Product</th><th scope="col">Combined<br /><small>RRF</small></th><th scope="col">Final</th><th scope="col">Change</th></tr></thead>
        <tbody>{products.map((product) => {
          const signals = product.signals;
          const before = signals?.pre_rerank_rank;
          const after = signals?.final_rank;
          const moved = before == null || after == null ? null : before - after;
          const isWanted = wanted !== null && wanted.tier !== "missing" && wanted.productId === product.product_id;
          return <tr key={product.product_id} className={highlightedId === product.product_id ? "is-highlighted" : undefined}
            data-wanted={isWanted ? wanted.tier : undefined}
            onMouseEnter={() => onHighlight(product.product_id)} onMouseLeave={() => onHighlight(null)}>
            <th scope="row">
              {isWanted ? <WantedBadge wanted={wanted} /> : null}
              <button type="button" title={product.title} onClick={() => onSelect(product.product_id)}
                onFocus={() => onHighlight(product.product_id)} onBlur={() => onHighlight(null)}>{product.title}</button>
              <small>{armLanguage.map((arm) => `${arm.label}: ${signals?.[arm.key]?.rank ?? "—"}`).join(" · ")}</small>
            </th>
            <td>{before == null ? "—" : `#${before}`}</td>
            <td>{after == null ? "—" : `#${after}`}</td>
            <td><Movement moved={moved} /></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <footer>
      <p>— means no recorded position. These are positions, not scores. Movement alone does not prove a better match; check the specifications.</p>
      {products.some((product) => product.signals?.exact_sku_match) ? <p>An exact listing match also takes priority in the final order.</p> : null}
      <Link href={playgroundQueryHref(response.query, response.applied_filters, response.search_event_id)}>Inspect the full search in Playground</Link>
    </footer>
  </aside>;
}
