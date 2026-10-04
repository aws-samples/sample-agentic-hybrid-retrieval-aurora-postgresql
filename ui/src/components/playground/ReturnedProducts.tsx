import { useState } from "react";
import { Link } from "wouter";
import { armLanguage } from "../../retrievalLanguage";
import type { ProductSummary } from "../../types";
import { pickName } from "../ask-mosaic/comparison";

type Order = "final" | "combined";
const SHOWN = 8;
const rank = (value: number | null | undefined) => (value == null ? "—" : `#${value}`);

/**
 * Every product the search returned, as tiles: the final order by default, or
 * the order fusion produced before reranking. Each tile opens its product and
 * offers its receipt; the dots say which methods found it.
 */
export function ReturnedProducts({ products, images, selectedId, onSelect }: {
  products: ProductSummary[];
  images: Map<number, string>;
  selectedId: number | null;
  onSelect: (productId: number) => void;
}) {
  const [order, setOrder] = useState<Order>("final");
  const [all, setAll] = useState(false);
  const sorted = [...products].sort((a, b) => (
    order === "final"
      ? (a.signals?.final_rank ?? Infinity) - (b.signals?.final_rank ?? Infinity)
      : (a.signals?.pre_rerank_rank ?? Infinity) - (b.signals?.pre_rerank_rank ?? Infinity)
  ));
  const shown = all ? sorted : sorted.slice(0, SHOWN);
  return (
    <div className="pg-returned">
      <div className="pg-returned-head">
        <div className="pg-seg" role="group" aria-label="Order">
          <button type="button" aria-pressed={order === "final"} onClick={() => setOrder("final")}>Final order</button>
          <button type="button" aria-pressed={order === "combined"} onClick={() => setOrder("combined")}>Before reranking (displayed products)</button>
        </div>
        <p className="pg-returned-key" aria-hidden="true">
          {armLanguage.map((arm) => <span key={arm.key} data-arm={arm.key}><i />{arm.label}</span>)}
        </p>
      </div>
      <ul className="pg-tiles" aria-label={order === "final" ? "Final ranking preview" : "Retrieved product preview"}>
        {shown.map((product) => {
          const signals = product.signals;
          const primary = order === "final" ? signals?.final_rank : signals?.pre_rerank_rank;
          const secondary = order === "final"
            ? `before reranking ${rank(signals?.pre_rerank_rank)}`
            : `final ${rank(signals?.final_rank)}`;
          return (
            <li key={product.product_id} data-selected={product.product_id === selectedId || undefined}>
              <Link href={`/products/${product.product_id}`} className="pg-tile-link">
                <span className="pg-tile-top"><b>{rank(primary)}</b><span>{secondary}</span></span>
                <span className="pg-tile-photo"><img src={images.get(product.product_id)} alt="" decoding="async" /></span>
                <span className="pg-tile-name">{pickName(product)}</span>
              </Link>
              <div className="pg-tile-foot">
                <span className="pg-tile-dots" role="img" aria-label={`Found by: ${armLanguage.filter((arm) => signals?.[arm.key].rank != null).map((arm) => arm.label).join(", ") || "no recorded method"}`}>
                  {armLanguage.map((arm) => <i key={arm.key} title={arm.label} data-arm={arm.key} data-found={signals?.[arm.key].rank != null || undefined} />)}
                </span>
                <button type="button" onClick={() => onSelect(product.product_id)} aria-label={`Receipt for ${product.title}`}>Receipt</button>
              </div>
            </li>
          );
        })}
      </ul>
      {sorted.length > SHOWN ? (
        <button type="button" className="pg-more" onClick={() => setAll((value) => !value)}>
          {all ? "Show fewer" : `Show all ${sorted.length}`}
        </button>
      ) : null}
    </div>
  );
}
