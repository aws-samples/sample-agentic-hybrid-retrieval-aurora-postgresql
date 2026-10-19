import { useState } from "react";
import { Link } from "wouter";
import type { WantedProduct } from "../labOutcome";
import { playgroundQueryHref } from "../navigation";
import type { SearchResponse } from "../types";
import { SearchChips } from "./ProductCard";
import { RankMove } from "./RankMove";
import { WantedBadge } from "./WantedBadge";
import "../shop-search-details.css";

export function ShopSearchDetails({
  response, images, onSelect, onHighlight, highlightedId, wanted = null, wantedName = null,
}: {
  response: SearchResponse;
  images: Map<number, string>;
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
      <p>Each search ranked these products. Aurora combined their positions, then the reranker reordered them.</p>
    </header>
    {!reranked ? <p>This request was not reranked, so the final order is the combined order.</p> : null}
    {wanted?.tier === "missing" ? <p className="shop-details-wanted">
      <WantedBadge wanted={wanted} />
      {wantedName ? <span>{wantedName}</span> : null}
    </p> : null}
    <div className="shop-details-order pg-seg" role="group" aria-label="Sort by">
      <button type="button" aria-pressed={order === "combined"} onClick={() => setOrder("combined")}>Combined order</button>
      <button type="button" aria-pressed={order === "final"} onClick={() => setOrder("final")}>Final order</button>
    </div>
    <div className="shop-details-table" tabIndex={0} role="region" aria-label="Product positions before and after reranking">
      <table>
        <caption>{products.length} {products.length === 1 ? "product" : "products"} shown{pool == null ? "" : `, of ${pool} ${reranked ? "reranked" : "combined"}`}. Positions, not scores.</caption>
        <thead><tr><th scope="col">Product</th><th scope="col">Combined</th><th scope="col">Final</th><th scope="col">Change</th></tr></thead>
        <tbody>{products.map((product) => {
          const signals = product.signals;
          const before = signals?.pre_rerank_rank ?? null;
          const after = signals?.final_rank ?? null;
          const isWanted = wanted !== null && wanted.tier !== "missing" && wanted.productId === product.product_id;
          return <tr key={product.product_id} className={highlightedId === product.product_id ? "is-highlighted" : undefined}
            data-wanted={isWanted ? wanted.tier : undefined}
            onMouseEnter={() => onHighlight(product.product_id)} onMouseLeave={() => onHighlight(null)}>
            <th scope="row">
              <div className="shop-details-product">
                <img src={images.get(product.product_id)} alt="" width={44} height={44} loading="lazy" decoding="async" />
                <div>
                  {isWanted ? <WantedBadge wanted={wanted} /> : null}
                  <button type="button" title={product.title} onClick={() => onSelect(product.product_id)}
                    onFocus={() => onHighlight(product.product_id)} onBlur={() => onHighlight(null)}>{product.title}</button>
                  <SearchChips product={product} />
                </div>
              </div>
            </th>
            <td>{before == null ? "—" : `#${before}`}</td>
            <td>{after == null ? "—" : `#${after}`}</td>
            <td>{after == null ? "—" : <RankMove from={before} to={after} />}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <footer>
      {products.some((product) => product.signals?.exact_sku_match) ? <p>An exact listing match also takes priority in the final order.</p> : null}
      <Link href={playgroundQueryHref(response.query, response.applied_filters, response.search_event_id)}>Watch the ranking change in the Playground</Link>
    </footer>
  </aside>;
}
