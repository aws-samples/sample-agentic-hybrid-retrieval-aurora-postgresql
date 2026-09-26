import { ArrowUpRight, ShoppingBag } from "lucide-react";
import { cartQuantityLimit, useCommerce } from "../../commerce";
import type { AgentResponse, ProductSummary } from "../../types";
import { ResultProductCard } from "../ResultProductCard";

/**
 * The recommended products, buyable.
 *
 * `recommendations` is the cited set the answer of record was written from, so
 * these are the same products the prose names - not a second, looser shortlist.
 * The bag button is the cart the rest of the store uses, so a participant can
 * finish the errand the answer started instead of reading about it.
 */
export function ShoppingResultCard({ product, position, imageByProductId, onHighlight, onSelectProduct }: {
  product: ProductSummary; position: number; imageByProductId: Map<number, string>;
  onHighlight: (productId: number | null) => void; onSelectProduct: (productId: number) => void;
}) {
  const { addItem, itemQuantity } = useCommerce();
  const inBag = itemQuantity(product.product_id);
  const limit = cartQuantityLimit(product);
  return <ResultProductCard product={product} imageSrc={imageByProductId.get(product.product_id)} rank={position}
    onHighlight={onHighlight} onSelect={onSelectProduct}
    footer={product.source_dataset ? (product.listing_url ? <a className="source-listing-link" href={product.listing_url} target="_blank" rel="noreferrer">View original listing <ArrowUpRight size={14} aria-hidden="true" /></a> : null) : <button className={inBag ? "ask-mosaic-pick-add in-bag" : "ask-mosaic-pick-add"} type="button" disabled={!limit || inBag >= limit} title={limit ? undefined : "Out of stock"} onClick={() => addItem(product)}><ShoppingBag size={14} aria-hidden="true" />{inBag ? `In bag (${inBag})` : "Add to bag"}</button>} />;
}

/**
 * What to ask next, written from this answer's own products.
 *
 * Every one of these routes to a tool the service registers: a comparison, a
 * ranking replay, and the specification and review records behind the leader.
 */
export function FollowUps({
  response,
  onRun,
}: {
  response: AgentResponse;
  onRun: (query: string) => void;
}) {
  const [first, second] = response.recommendations;
  if (!second) return null;
  return (
    <div className="ask-mosaic-followups" aria-label="Ask Mosaic follow-up actions">
      <button
        type="button"
        onClick={() => onRun(
          `Compare ${first.model} with ${second.model} and explain the decisive trade-offs.`,
        )}
      >
        Compare top two
      </button>
      <button
        type="button"
        onClick={() => onRun(
          `Explain why ${first.model} ranked first, using what the search and the evidence show.`,
        )}
      >
        Why this one?
      </button>
      <button
        type="button"
        onClick={() => onRun(`What do the specs and reviews say about ${first.model}?`)}
      >
        What do reviews say?
      </button>
    </div>
  );
}
