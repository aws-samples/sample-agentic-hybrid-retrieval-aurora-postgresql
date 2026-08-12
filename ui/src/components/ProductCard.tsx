import { Check, Heart, ShoppingBag, Star } from "lucide-react";
import { Link } from "wouter";
import { useCommerce } from "../commerce";
import { formatAvailability, formatPrice, isPurchasable, leafCategory } from "../format";
import { productImage } from "../media";
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
  collectionLabels = [],
  variant = "default",
  assistRank,
  highlighted = false,
}: {
  product: ProductSummary;
  showSignals?: boolean;
  showCompare?: boolean;
  collectionLabels?: string[];
  variant?: "default" | "catalog";
  assistRank?: number;
  highlighted?: boolean;
}) {
  const {
    addItem,
    isFavorite,
    itemQuantity,
    toggleFavorite,
  } = useCommerce();
  const saved = isFavorite(product.product_id);
  const quantity = itemQuantity(product.product_id);
  const signals = product.signals;
  const productTags = product.tags.filter((tag): tag is string => typeof tag === "string");
  const tags = Array.from(new Set([...collectionLabels, ...productTags])).slice(0, 3);

  if (variant === "catalog") {
    return (
      <article
        className={[
          "product-card catalog-product-card",
          assistRank ? "assist-selected" : "",
          highlighted ? "assist-highlighted" : "",
        ].filter(Boolean).join(" ")}
      >
        <Link className="product-image" href={`/products/${product.product_id}`}>
          <img
            src={productImage(product)}
            alt=""
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
          <p className="catalog-card-brand">
            {product.brand}
            <span>{leafCategory(product.category_path)}</span>
          </p>
          <h3>
            <Link href={`/products/${product.product_id}`}>{product.model}</Link>
          </h3>
          <div className="catalog-card-evidence">
            {product.review_count && product.rating !== null ? (
              <span className="catalog-card-rating">
                <Star size={14} fill="currentColor" />
                <b>{product.rating.toFixed(1)}</b>
                <small>({product.review_count.toLocaleString()})</small>
              </span>
            ) : <span className="catalog-card-rating muted">New arrival</span>}
            <span className={isPurchasable(product.availability) ? "catalog-card-stock" : "catalog-card-stock unavailable"}>
              <i />
              {formatAvailability(product.availability)}
            </span>
          </div>
          {collectionLabels.length ? (
            <div className="catalog-product-tags">
              {tags.slice(0, 1).map((tag) => (
                <span className={collectionLabels.includes(tag) ? "match-tag" : ""} key={tag}>{tag}</span>
              ))}
            </div>
          ) : null}
          {showSignals && signals ? (
            <div className="catalog-signal-strip">
              <span>FTS {signals.fts.rank ?? "-"}</span>
              <span>VEC {signals.semantic.rank ?? "-"}</span>
              <span>RRF {signals.pre_rerank_rank}</span>
              <span>FINAL {signals.final_rank}</span>
            </div>
          ) : null}
          <div className="catalog-card-buy">
            <span>
              <strong>{formatPrice(product.price_cents, product.currency)}</strong>
              {product.list_price_cents > product.price_cents ? (
                <small>{formatPrice(product.list_price_cents, product.currency)}</small>
              ) : null}
            </span>
            <button
              className={quantity ? "catalog-cart-button added" : "catalog-cart-button"}
              type="button"
              disabled={!isPurchasable(product.availability)}
              aria-label={
                quantity
                  ? `Add another ${product.title} to cart`
                  : `Add ${product.title} to cart`
              }
              onClick={() => addItem(product)}
            >
              {quantity ? <Check size={16} /> : <ShoppingBag size={16} />}
              <span>{quantity ? `Added (${quantity})` : "Add to cart"}</span>
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
          src={productImage(product)}
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
        {showSignals && signals ? (
          <div className="signal-strip">
            <span>FTS {signals.fts.rank ?? "-"}</span>
            <span>Trigram {signals.trigram.rank ?? "-"}</span>
            <span>Vector {signals.semantic.rank ?? "-"}</span>
            <span>Rerank {signals.rerank_score?.toFixed(3) ?? "-"}</span>
          </div>
        ) : null}
        <div className="product-card-actions">
          {showCompare ? (
            <label className="compare-control">
              <input type="checkbox" />
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
