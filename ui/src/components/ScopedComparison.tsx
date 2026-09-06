import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProductSummary, RankSignal } from "../types";

/**
 * A side-by-side over products one retrieval granted, read back from the server.
 *
 * The obvious way to build this is to filter the result array the page already
 * holds. That version cannot be wrong about price, and cannot be right about
 * anything else: the client has no receipt, so it cannot say which arm found a
 * product or where reranking moved it, and nothing checks that the products
 * being compared were ever granted by a retrieval at all.
 *
 * So the panel asks `POST /api/retrieval/events/{id}/compare` instead. That
 * endpoint retrieves nothing -- no fusion, no rerank, no candidate generation --
 * it reads the persisted receipt and hydrates catalog rows, which is what lets
 * the ranking row below exist. It is unbilled and repeatable.
 *
 * The refusal matters as much as the answer. A product outside the granted
 * window comes back 404 with a detail naming no product, so a comparison cannot
 * be used to ask whether something exists. That is the reason the panel reports
 * the server's refusal rather than quietly dropping the row.
 */

/** Which arms found a product, in the order the workshop teaches them. */
const ARMS = [
  ["fts", "Full text"],
  ["trigram", "Trigram"],
  ["semantic", "Semantic"],
] as const;

function armRank(product: ProductSummary, arm: (typeof ARMS)[number][0]): RankSignal | null {
  return product.signals ? product.signals[arm] : null;
}

/** The arms that actually placed this product, named rather than numbered. */
function foundBy(product: ProductSummary): string {
  const hits = ARMS.filter(([arm]) => armRank(product, arm)?.rank != null).map(
    ([, label]) => label.toLowerCase(),
  );
  return hits.length ? hits.join(", ") : "not in any arm";
}

function priceDisplay(product: ProductSummary): string {
  return `$${(product.price_cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function ScopedComparison({
  searchEventId,
  productIds,
  onClear,
}: {
  /** The retrieval whose grant authorises this comparison. */
  searchEventId: string;
  productIds: number[];
  onClear: () => void;
}) {
  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [error, setError] = useState("");
  /**
   * The request key, not a boolean. Selecting a third product while the second
   * request is in flight would otherwise let the older response land last and
   * render a comparison the participant is no longer asking for.
   */
  const requestKey = `${searchEventId}:${[...productIds].sort((a, b) => a - b).join(",")}`;

  useEffect(() => {
    let current = true;
    setError("");
    api.compareScopedProducts(searchEventId, productIds).then(
      (response) => {
        if (current) setProducts(response.products);
      },
      (reason: unknown) => {
        if (!current) return;
        setProducts(null);
        setError(reason instanceof Error ? reason.message : "Comparison failed.");
      },
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  return (
    <section className="shop-comparison" aria-label="Comparing selected products">
      <div className="shop-comparison-heading">
        <h2>
          Comparing {productIds.length} of your results
        </h2>
        <button type="button" onClick={onClear}>
          Clear selection
        </button>
      </div>

      {error ? (
        <p className="shop-comparison-error">{error}</p>
      ) : !products ? (
        <p className="shop-comparison-pending">Reading the retrieval receipt…</p>
      ) : (
        <div className="shop-comparison-scroll">
          <table className="shop-comparison-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Field</span>
                </th>
                {products.map((product) => (
                  <th scope="col" key={product.product_id}>
                    {product.title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Price</th>
                {products.map((product) => (
                  <td key={product.product_id}>{priceDisplay(product)}</td>
                ))}
              </tr>
              <tr>
                <th scope="row">Rating</th>
                {products.map((product) => (
                  <td key={product.product_id}>{product.rating ?? "not rated"}</td>
                ))}
              </tr>
              <tr>
                <th scope="row">Availability</th>
                {products.map((product) => (
                  <td key={product.product_id}>{product.availability.replace(/_/g, " ")}</td>
                ))}
              </tr>
              {/* Everything below comes from the retrieval receipt, and is the
                  reason this panel asks the server rather than filtering the
                  list the page already had. */}
              <tr className="shop-comparison-rule">
                <th scope="row">Found by</th>
                {products.map((product) => (
                  <td key={product.product_id}>{foundBy(product)}</td>
                ))}
              </tr>
              <tr>
                <th scope="row">Rank before reranking</th>
                {products.map((product) => (
                  <td key={product.product_id}>
                    {product.signals ? product.signals.pre_rerank_rank : "not recorded"}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Rank shown to you</th>
                {products.map((product) => (
                  <td key={product.product_id}>
                    {product.signals ? product.signals.final_rank : "not recorded"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
