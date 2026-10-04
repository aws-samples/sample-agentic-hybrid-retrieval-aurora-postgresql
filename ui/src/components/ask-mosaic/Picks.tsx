import { ArrowUpRight, Check, ShoppingBag, X } from "lucide-react";
import { cartQuantityLimit, useCommerce } from "../../commerce";
import { productImage } from "../../media";
import type { AgentCitation, ProductSummary } from "../../types";
import { CitePills } from "./citations";
import { pickName, retrievalPath, type ComparisonRow } from "./comparison";
import { pickFacts, pickRequirements, type PickRequirement } from "./pickFacts";

interface PickProps {
  product: ProductSummary;
  /** The pick's column in `rows`. */
  index: number;
  rows: ComparisonRow[];
  citations: AgentCitation[];
  answerId: string;
  imageSrc?: string;
  /** Builder view: print where search found it. */
  builder: boolean;
  /** Shop is pointing at this product, or the reader is pointing at it here. */
  highlighted: boolean;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

/** A demo-catalog pick goes in the bag; a real listing links to its source. */
function PickAction({ product }: { product: ProductSummary }) {
  const { addItem, itemQuantity } = useCommerce();
  if (product.listing_url) {
    return (
      <a className="ask-pill-action" href={product.listing_url} target="_blank" rel="noreferrer">
        Listing <ArrowUpRight size={12} aria-hidden="true" />
      </a>
    );
  }
  if (product.source_dataset) return null;
  const inBag = itemQuantity(product.product_id);
  const limit = cartQuantityLimit(product);
  return (
    <button
      className="ask-pill-action"
      type="button"
      disabled={!limit || inBag >= limit}
      title={limit ? undefined : "Out of stock"}
      onClick={() => addItem(product)}
    >
      <ShoppingBag size={12} aria-hidden="true" />
      {inBag ? `In bag (${inBag})` : "Add to bag"}
    </button>
  );
}

/** Pointing at a pick lights its card in Shop, the way the shortlist used to. */
function pointing(product: ProductSummary, onHighlight: (productId: number | null) => void) {
  return {
    onMouseEnter: () => onHighlight(product.product_id),
    onMouseLeave: () => onHighlight(null),
    onFocus: () => onHighlight(product.product_id),
    onBlur: () => onHighlight(null),
  };
}

function Requirement({ item, answerId }: { item: PickRequirement; answerId: string }) {
  const met = item.status === "met";
  return (
    <p className={`ask-requirement ${met ? "is-met" : "is-not-met"}`}>
      {met ? <Check size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />}
      <span>
        {met ? "Meets" : "Short of"} {item.label}
        {met ? "" : `: the listing states ${item.value}`}
      </span>
      <CitePills numbers={item.citations} answerId={answerId} />
    </p>
  );
}

function Path({ product }: { product: ProductSummary }) {
  const path = retrievalPath(product);
  return path.length ? <p className="ask-mono ask-path" aria-label="How search found it">{path.join(" → ")}</p> : null;
}

/** The photograph a shopper recognises, the pick's name and the cited facts that earn it a place. */
export function TopPick({ product, index, rows, citations, answerId, imageSrc, builder, highlighted, onHighlight, onSelectProduct }: PickProps) {
  const name = pickName(product);
  return (
    <article
      className="ask-top-pick"
      aria-label={`Top pick: ${name}`}
      data-highlighted={highlighted || undefined}
      {...pointing(product, onHighlight)}
    >
      <button
        type="button"
        className="ask-pick-photo"
        onClick={() => onSelectProduct(product.product_id)}
        aria-label={`Open ${name}`}
      >
        <img src={imageSrc ?? productImage(product)} alt="" loading="lazy" decoding="async" />
      </button>
      <div className="ask-top-pick-copy">
        <div className="ask-top-pick-head">
          <h4>{name}</h4>
          <span className="ask-pill ask-pill-neutral"><i className="ask-dot" aria-hidden="true" />Top pick</span>
        </div>
        {pickFacts(product, citations).map((fact) => (
          <p className="ask-fact" key={fact.text}>
            <span>{fact.text}</span>
            {fact.number != null ? <CitePills numbers={[fact.number]} answerId={answerId} /> : null}
          </p>
        ))}
        {pickRequirements(rows, index).map((item) => (
          <Requirement key={item.label} item={item} answerId={answerId} />
        ))}
        {builder ? <Path product={product} /> : null}
        <PickAction product={product} />
      </div>
    </article>
  );
}

/** The remaining recommendations, one compact row each. */
export function PickRow({ product, index, rows, citations, answerId, imageSrc, builder, highlighted, onHighlight, onSelectProduct }: PickProps) {
  const name = pickName(product);
  const [fact] = pickFacts(product, citations);
  return (
    <li className="ask-pick-row" data-highlighted={highlighted || undefined} {...pointing(product, onHighlight)}>
      <button
        type="button"
        className="ask-pick-photo is-small"
        onClick={() => onSelectProduct(product.product_id)}
        aria-label={`Open ${name}`}
      >
        <img src={imageSrc ?? productImage(product)} alt="" loading="lazy" decoding="async" />
      </button>
      <div className="ask-pick-row-copy">
        <strong>{name}</strong>
        {fact ? (
          <p className="ask-fact">
            <span>{fact.text}</span>
            {fact.number != null ? <CitePills numbers={[fact.number]} answerId={answerId} /> : null}
          </p>
        ) : null}
        {pickRequirements(rows, index).map((item) => (
          <Requirement key={item.label} item={item} answerId={answerId} />
        ))}
        {builder ? <Path product={product} /> : null}
      </div>
      <PickAction product={product} />
    </li>
  );
}
