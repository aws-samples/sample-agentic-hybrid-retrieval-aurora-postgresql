import { Check, Heart, ShoppingBag, Star } from "lucide-react";
import { Link } from "wouter";
import { cartQuantityLimit, useCommerce } from "../commerce";
import { formatAvailability, formatPrice, isPurchasable, leafCategory } from "../format";
import { productImage } from "../media";
import { FINAL_LABEL, FUSED_LABEL, armLabel } from "../retrievalLanguage";
import type { ProductSummary } from "../types";

function topAttributes(attributes: Record<string, unknown>, count = 2) {
  return Object.entries(attributes)
    .filter(([, value]) => typeof value !== "object")
    .slice(0, count)
    .map(([key, value]) => ({
      label: key.replaceAll("_", " "),
      value: typeof value === "boolean" ? (value ? "Yes" : "No") : String(value),
    }));
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
    return (
      <article
        className={[
          "shop-product-card",
          assistRank ? "assist-selected" : "",
          highlighted ? "assist-highlighted" : "",
        ].filter(Boolean).join(" ")}
        data-product-id={product.product_id}
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
        <Link className="product-image" href={`/products/${product.product_id}`}>
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
        <div className="product-card-body">
          <p className="shop-card-kicker">
            <span>{product.brand}</span>
            {leafCategory(product.category_path)}
          </p>
          <h3>
            <Link href={`/products/${product.product_id}`}>{product.model}</Link>
          </h3>
          {/* "Why this match", not "Why ranked #3": a shopper deciding between two
              chairs is asking what Mosaic noticed, and the number is inside. Every
              row is one product's own position, never a pool count. */}
          {showSignals && signals ? (
            <details className="shop-card-signals">
              <summary aria-label={`Why ${product.model} is a match`}>
                Why this match
              </summary>
              <dl>
                {signals.fts.rank ? (
                  <div>
                    <dt>{armLabel.fts}</dt>
                    <dd>#{signals.fts.rank}</dd>
                  </div>
                ) : null}
                {signals.trigram.rank ? (
                  <div>
                    <dt>{armLabel.trigram}</dt>
                    <dd>#{signals.trigram.rank}</dd>
                  </div>
                ) : null}
                {signals.semantic.rank ? (
                  <div>
                    <dt>{armLabel.semantic}</dt>
                    <dd>#{signals.semantic.rank}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>{FUSED_LABEL}</dt>
                  <dd>#{signals.pre_rerank_rank}</dd>
                </div>
                <div>
                  <dt>{FINAL_LABEL}</dt>
                  <dd>#{signals.final_rank}</dd>
                </div>
              </dl>
            </details>
          ) : null}
          <div className="shop-card-footer">
            <span className="shop-card-price">
              <strong>{formatPrice(product.price_cents, product.currency)}</strong>
              {product.review_count && product.rating !== null ? (
                <span className="shop-card-rating">
                  <Star size={13} fill="currentColor" />
                  {product.rating.toFixed(1)}
                </span>
              ) : null}
              {isPurchasable(product.availability) ? null : (
                <span className="shop-card-stock unavailable">
                  {formatAvailability(product.availability)}
                </span>
              )}
            </span>
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
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="product-card">
      <Link className="product-image" href={`/products/${product.product_id}`}>
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
          <Link href={`/products/${product.product_id}`}>{product.title}</Link>
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
          {topAttributes(product.attributes).map((attribute) => (
            <div key={attribute.label}>
              <dt>{attribute.label}</dt>
              <dd>{attribute.value}</dd>
            </div>
          ))}
        </dl>
        {/* The same five words the catalog card uses. This strip printed "FTS 3 /
            Trigram 7 / Vector 2 / Rerank 0.841", which is the mechanism, not the
            match, on a card a shopper is reading to choose a product. */}
        {showSignals && signals ? (
          <div className="signal-strip">
            <span>{armLabel.fts} #{signals.fts.rank ?? "-"}</span>
            <span>{armLabel.trigram} #{signals.trigram.rank ?? "-"}</span>
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
          <Link className="product-detail-link" href={`/products/${product.product_id}`}>
            View details
          </Link>
        </div>
      </div>
    </article>
  );
}
