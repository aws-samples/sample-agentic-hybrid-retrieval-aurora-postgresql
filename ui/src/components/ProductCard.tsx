import { Check, Heart, Plus, ShoppingBag, Star } from "lucide-react";
import { Fragment } from "react";
import { Link } from "wouter";
import { cartQuantityLimit, useCommerce } from "../commerce";
import { formatAvailability, formatPrice, isPurchasable, leafCategory, listingPriceCents, specFacts } from "../format";
import { productDetailHref } from "../navigation";
import { productImage } from "../media";
import { ProductReceiptBody } from "./ProductReceipt";
import { FINAL_LABEL, armLabel, armLanguage, armShortLabel } from "../retrievalLanguage";
import type { WantedProduct } from "../labOutcome";
import { RankMove } from "./RankMove";
import { WantedBadge } from "./WantedBadge";
import type { ProductSummary, RetrievalDiagnostics } from "../types";
import "../pipeline-strip.css";

/**
 * The typed spec facts as one quiet line, e.g. "Screen size 27″ · Resolution
 * 3840 × 2160 · USB-C power 90W". The same `specFacts` the receipt and the
 * product page read, so a fact printed on the tile is a fact the listing
 * itself states, not free-text copy.
 */
function specFactParts(product: ProductSummary, count = 3) {
  return specFacts(product.specs, count);
}

function topAttributes(attributes: Record<string, unknown>, count = 2) {
  return Object.entries(attributes)
    .filter(([, value]) => typeof value !== "object")
    .slice(0, count)
    .map(([key, value]) => ({
      label: key.replaceAll("_", " "),
      value: typeof value === "boolean" ? (value ? "Yes" : "No") : String(value),
    }));
}

/**
 * The searches that found this product, on the card itself: a green dot and the
 * product's own position for each search that returned it, a hollow grey dot
 * and a dash for each that did not. Positions are read from the row's signals.
 */
/**
 * The product's way through this search, in the terminal's words: each search
 * that found it with its rank, then its combined position and its final one.
 * `lab_terminal.py` prints the same run as "combined position 21, final
 * position 5, found by semantic search rank 10". A search that did not find it
 * is left out here; the strip and Why this match say so.
 */
function RankLine({ product }: { product: ProductSummary }) {
  const signals = product.signals;
  if (!signals) return null;
  const before = signals.pre_rerank_rank;
  const after = signals.final_rank;
  const found = armLanguage.filter((arm) => signals[arm.key]?.rank != null);
  return (
    <div className="shop-card-rankline">
      {found.length ? (
        <p className="shop-card-found" aria-label="Found by">
          {found.map((arm) => `${armShortLabel[arm.key]} #${signals[arm.key]!.rank}`).join(" + ")}
        </p>
      ) : null}
      {after != null ? (
        <p className="shop-card-position-chip">
          {before != null ? <span>Combined #{before} →</span> : null}
          <b>Final #{after}</b>
          {before != null && before !== after ? <RankMove from={before} to={after} /> : null}
        </p>
      ) : null}
    </div>
  );
}

export function ProductCard({
  product,
  showSignals = false,
  showCompare = false,
  compareChecked = false,
  compareDisabled = false,
  onCompareChange,
  collectionLabels = [],
  variant = "default",
  imageSrc,
  assistRank,
  highlighted = false,
  onAssistFocus,
  diagnostics,
  wanted,
}: {
  product: ProductSummary;
  showSignals?: boolean;
  showCompare?: boolean;
  compareChecked?: boolean;
  compareDisabled?: boolean;
  onCompareChange?: (productId: number, checked: boolean) => void;
  collectionLabels?: string[];
  variant?: "default" | "catalog";
  /** Grid-assigned photograph. Omit outside a result set. */
  imageSrc?: string;
  assistRank?: number;
  highlighted?: boolean;
  onAssistFocus?: (productId: number | null) => void;
  /** The search's diagnostics, for the receipt's k and reranking-pool figures. */
  diagnostics?: RetrievalDiagnostics | null;
  /** The active lab's wanted product, when this card is it and the run returned it. */
  wanted?: WantedProduct | null;
}) {
  const {
    addItem,
    isFavorite,
    itemQuantity,
    toggleFavorite,
  } = useCommerce();
  const saved = isFavorite(product.product_id);
  const quantity = itemQuantity(product.product_id);
  const quantityLimit = cartQuantityLimit(product);
  const quantityAtLimit = quantity > 0 && quantity >= quantityLimit;
  const signals = product.signals;
  const productTags = product.tags.filter((tag): tag is string => typeof tag === "string");
  const tags = Array.from(new Set([...collectionLabels, ...productTags])).slice(0, 3);

  if (variant === "catalog") {
    const facts = specFactParts(product);
    const shownPriceCents = listingPriceCents(product);
    return (
      <article
        className={[
          "shop-product-card",
          product.source_dataset ? "source-product-card" : "",
          assistRank ? "assist-selected" : "",
          highlighted ? "assist-highlighted" : "",
        ].filter(Boolean).join(" ")}
        data-product-id={product.product_id}
        data-wanted={wanted?.tier}
        onMouseEnter={() => {
          if (assistRank) onAssistFocus?.(product.product_id);
        }}
        onMouseLeave={() => {
          if (assistRank) onAssistFocus?.(null);
        }}
        onFocusCapture={() => {
          if (assistRank) onAssistFocus?.(product.product_id);
        }}
        onBlurCapture={(event) => {
          if (
            assistRank
            && !event.currentTarget.contains(event.relatedTarget as Node | null)
          ) {
            onAssistFocus?.(null);
          }
        }}
      >
        <div className="shop-card-photo">
          <Link className="product-image" href={productDetailHref(product.product_id)}>
            <img
              src={imageSrc ?? productImage(product)}
              alt={product.title}
              width={1200}
              height={800}
              loading="lazy"
              decoding="async"
            />
            {assistRank ? <span className="assist-rank-badge">{String(assistRank).padStart(2, "0")}</span> : null}
          </Link>
          {showCompare ? (
              <label className="compare-control shop-card-compare" title="Compare" data-checked={compareChecked || undefined}>
                <input
                  type="checkbox"
                  aria-label={`Compare ${product.title}`}
                  checked={compareChecked}
                  disabled={compareDisabled || !onCompareChange}
                  onChange={(event) => {
                    onCompareChange?.(product.product_id, event.currentTarget.checked);
                  }}
                />
                {compareChecked ? <Check size={15} aria-hidden="true" /> : <Plus size={15} aria-hidden="true" />}
              </label>
            ) : null}
          <button
            className={saved ? "catalog-favorite-button active" : "catalog-favorite-button"}
            type="button"
            aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`}
            title={saved ? "Remove saved product" : "Save product"}
            aria-pressed={saved}
            onClick={() => toggleFavorite(product.product_id)}
          >
            <Heart size={18} fill={saved ? "currentColor" : "none"} />
          </button>
        </div>
        <div className="product-card-body">
          {wanted ? <WantedBadge wanted={wanted} /> : null}
          <h3>
            <Link href={productDetailHref(product.product_id)}>{product.source_dataset ? product.title : product.model}</Link>
          </h3>
          {showSignals ? null : (
            <p className="shop-card-meta">
              <span>{product.brand}</span>
              {leafCategory(product.category_path)}
            </p>
          )}
          {facts.length ? (
            <p className="shop-card-facts">
              {facts.map((fact, index) => (
                <Fragment key={fact.label}>
                  {index ? " · " : null}
                  <span className="shop-card-fact">{`${fact.label} ${fact.value}`}</span>
                </Fragment>
              ))}
            </p>
          ) : null}
          <div className="shop-card-price">
            {shownPriceCents == null && product.source_dataset ? (
              <strong
                className="shop-card-price-none"
                role="img"
                aria-label="Price not recorded"
                title="No price recorded in the original listing. Open the listing for the current price."
              >
                –
              </strong>
            ) : (
              <strong title={product.source_dataset ? "Historical price from the original listing" : undefined}>
                {formatPrice(shownPriceCents, product.currency)}
              </strong>
            )}
            {product.review_count && product.rating !== null ? (
              <span className="shop-card-rating" title={product.source_dataset ? `${product.review_count.toLocaleString()} historical ratings` : undefined}>
                <Star size={13} fill="currentColor" />
                {product.rating.toFixed(1)}
              </span>
            ) : null}
            {!product.source_dataset && !isPurchasable(product.availability) ? (
              <span className="shop-card-stock unavailable">
                {formatAvailability(product.availability)}
              </span>
            ) : null}
          </div>
          {showSignals && signals ? <RankLine product={product} /> : null}
          {/* "Why this match", not "Why ranked #3": a shopper deciding between two
              chairs is asking what Mosaic noticed, and the number is inside. Every
              row is one product's own position, never a pool count. */}
          <div className="shop-card-actions">
          {showSignals && signals ? (
            <details
              className="shop-card-signals"
              onToggle={(event) => {
                // Opening moves keyboard focus into the receipt; closing returns it to the summary.
                const details = event.currentTarget;
                if (details.open) details.querySelector<HTMLElement>(".shop-card-receipt")?.focus();
                else if (details.contains(document.activeElement)) details.querySelector("summary")?.focus();
              }}
            >
              <summary>Why this match</summary>
              <div className="shop-card-receipt" tabIndex={-1} aria-label="Why this match">
                <ProductReceiptBody product={product} diagnostics={diagnostics} />
              </div>
            </details>
          ) : null}
          <div className="shop-card-footer">
            {/* Same control and same class as the default variant below, so the
                two surfaces cannot drift into two compare affordances. It is
                rendered only where a retrieval has granted a scope to compare
                within, which is why the caller decides rather than the card. */}
            {product.listing_url ? <a className="source-listing-link" href={product.listing_url} target="_blank" rel="noreferrer" aria-label={`Original listing for ${product.title}`}>Listing ↗</a> : (
            <button
              className={quantity ? "shop-quick-add added" : "shop-quick-add"}
              type="button"
              disabled={!quantityLimit || quantityAtLimit}
              aria-label={
                quantityAtLimit
                  ? `${product.title} quantity limit reached`
                  : quantity
                  ? `Add another ${product.title} to cart`
                  : `Add ${product.title} to cart`
              }
              title={
                quantityAtLimit
                  ? `Maximum ${quantityLimit} in bag`
                  : quantity
                    ? `Add another (${quantity} in bag)`
                    : "Add to bag"
              }
              onClick={() => addItem(product)}
            >
              <ShoppingBag size={17} />
              {quantity ? <span>{quantity}</span> : null}
            </button>
            )}
          </div>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="product-card">
      <Link className="product-image" href={productDetailHref(product.product_id)} aria-label={`View ${product.title}`}>
        <img
          src={imageSrc ?? productImage(product)}
          alt=""
          width={1200}
          height={800}
          loading="lazy"
          decoding="async"
        />
        {signals ? <span className="rank-badge">#{signals.final_rank}</span> : null}
      </Link>
      <button
        className={saved ? "favorite-button active" : "favorite-button"}
        type="button"
        aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`}
        title={saved ? "Remove saved product" : "Save product"}
        aria-pressed={saved}
        onClick={() => toggleFavorite(product.product_id)}
      >
        <Heart size={17} fill={saved ? "currentColor" : "none"} />
      </button>
      <div className="product-card-body">
        <p className="eyebrow">{leafCategory(product.category_path)}</p>
        <h3>
          <Link href={productDetailHref(product.product_id)}>{product.title}</Link>
        </h3>
        <div className="price-row">
          <strong>{formatPrice(product.price_cents, product.currency)}</strong>
          <span className={isPurchasable(product.availability) ? "stock" : "muted"}>
            {isPurchasable(product.availability) ? <Check size={14} /> : null}
            {formatAvailability(product.availability)}
          </span>
        </div>
        {product.review_count && product.rating !== null ? (
          <div className="rating-row">
            <Star size={15} fill="currentColor" />
            <strong>{product.rating.toFixed(1)}</strong>
            <span>{product.review_count.toLocaleString()} reviews</span>
          </div>
        ) : null}
        {tags.length ? (
          <div className="product-tags">
            {tags.map((tag) => (
              <span className={collectionLabels.includes(tag) ? "match-tag" : ""} key={tag}>{tag}</span>
            ))}
          </div>
        ) : null}
        <dl className="attribute-list">
          {(product.specs && Object.keys(product.specs).length
            ? specFacts(product.specs, 2)
            : topAttributes(product.attributes)
          ).map((attribute) => (
            <div key={attribute.label}>
              <dt>{attribute.label}</dt>
              <dd>{attribute.value}</dd>
            </div>
          ))}
        </dl>
        {/* The same five words the catalog card uses. This strip printed "FTS 3 /
            Fuzzy 7 / Semantic 2 / Rerank 0.841", which is the mechanism, not the
            match, on a card a shopper is reading to choose a product. */}
        {showSignals && signals ? (
          <div className="signal-strip">
            <span>{armLabel.fts} #{signals.fts.rank ?? "-"}</span>
            <span>{armLabel.fuzzy} #{signals.fuzzy.rank ?? "-"}</span>
            <span>{armLabel.semantic} #{signals.semantic.rank ?? "-"}</span>
            <span>{FINAL_LABEL} #{signals.final_rank}</span>
          </div>
        ) : null}
        <div className="product-card-actions">
          {showCompare ? (
            <label className="compare-control">
              <input
                type="checkbox"
                aria-label={`Compare ${product.title}`}
                checked={compareChecked}
                disabled={compareDisabled || !onCompareChange}
                onChange={(event) => {
                  onCompareChange?.(product.product_id, event.currentTarget.checked);
                }}
              />
              Compare
            </label>
          ) : null}
          <Link className="product-detail-link" href={productDetailHref(product.product_id)}>
            View details
          </Link>
        </div>
      </div>
    </article>
  );
}
