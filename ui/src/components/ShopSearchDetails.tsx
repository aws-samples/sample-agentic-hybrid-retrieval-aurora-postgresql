import { useState } from "react";
import { Link } from "wouter";
import { playgroundQueryHref } from "../navigation";
import { armLanguage } from "../retrievalLanguage";
import type { SearchResponse } from "../types";
import "../shop-search-details.css";

export function ShopSearchDetails({ response, onSelect, onHighlight, highlightedId }: {
  response: SearchResponse;
  onSelect: (id: number) => void;
  onHighlight: (id: number | null) => void;
  highlightedId: number | null;
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
      <p>RRF combines positions from word, spelling and meaning searches. The reranker then compares those products with your full request.</p>
    </header>
    {!reranked ? <p>This request was not reranked. Final positions may reflect the combined order or an exact listing match.</p> : null}
    <div className="shop-details-order" role="group" aria-label="Order the search details">
      <button type="button" aria-pressed={order === "combined"} onClick={() => setOrder("combined")}>Combined order</button>
      <button type="button" aria-pressed={order === "final"} onClick={() => setOrder("final")}>Final order</button>
    </div>
    <p className="shop-details-scope">Same {products.length} displayed products{pool == null ? "" : ` from ${pool} ${reranked ? "sent to reranking" : "in the combined list"}`}. Gaps in positions belong to other products in that list.</p>
    <div className="shop-details-table" tabIndex={0} role="region" aria-label="Product positions before and after reranking">
      <table>
        <caption>Positions from this saved search. Up means a product moved closer to first.</caption>
        <thead><tr><th scope="col">Product</th><th scope="col">Combined<br /><small>RRF</small></th><th scope="col">Final</th><th scope="col">Change</th></tr></thead>
        <tbody>{products.map((product) => {
          const signals = product.signals;
          const before = signals?.pre_rerank_rank;
          const after = signals?.final_rank;
          const moved = before == null || after == null ? null : before - after;
          return <tr key={product.product_id} className={highlightedId === product.product_id ? "is-highlighted" : undefined}
            onMouseEnter={() => onHighlight(product.product_id)} onMouseLeave={() => onHighlight(null)}>
            <th scope="row">
              <button type="button" title={product.title} onClick={() => onSelect(product.product_id)}
                onFocus={() => onHighlight(product.product_id)} onBlur={() => onHighlight(null)}>{product.title}</button>
              <small>{armLanguage.map((arm) => `${arm.label}: ${signals?.[arm.key]?.rank ?? "—"}`).join(" · ")}</small>
            </th>
            <td>{before == null ? "—" : `#${before}`}</td>
            <td>{after == null ? "—" : `#${after}`}</td>
            <td className={moved && moved > 0 ? "moved-up" : undefined}>{moved == null ? "—" : moved === 0 ? "Held" : `${moved > 0 ? "↑" : "↓"} ${Math.abs(moved)}`}</td>
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
