import { Check, Heart, Star } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
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
}: {
  product: ProductSummary;
  showSignals?: boolean;
  showCompare?: boolean;
  collectionLabels?: string[];
  variant?: "default" | "catalog";
}) {
  const [saved, setSaved] = useState(false);
  const signals = product.signals;
  const productTags = product.tags.filter((tag): tag is string => typeof tag === "string");
  const tags = Array.from(new Set([...collectionLabels, ...productTags])).slice(0, 3);

  if (variant === "catalog") {
    return (
      <article className="product-card catalog-product-card">
        <Link className="product-image" href={`/products/${product.product_id}`}>
          <img src={productImage(product)} alt="" />
        </Link>
        <button
          className={saved ? "catalog-favorite-button active" : "catalog-favorite-button"}
          type="button"
          aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`}
          title={saved ? "Remove saved product" : "Save product"}
          onClick={() => setSaved((current) => !current)}
        >
          <Heart size={18} fill={saved ? "currentColor" : "none"} />
        </button>
        <div className="product-card-body">
          <h3>
            <Link href={`/products/${product.product_id}`}>{product.model}</Link>
          </h3>
          <p className="product-category">{leafCategory(product.category_path)}</p>
          <div className="catalog-card-bottom">
            <strong>{formatPrice(product.price_cents, product.currency)}</strong>
            {/* No stars without reviews: the local preview seed carries a rating
                with review_count 0, and showing it implies evidence that the
                loaded catalog does not have. */}
            {product.review_count && product.rating !== null ? (
              <span>
                <Star size={14} fill="currentColor" />
                {product.rating.toFixed(1)}
                {` (${product.review_count.toLocaleString()})`}
              </span>
            ) : null}
          </div>
          {tags.length ? (
            <div className="catalog-product-tags">
              {tags.slice(0, 1).map((tag) => (
                <span className={collectionLabels.includes(tag) ? "match-tag" : ""} key={tag}>{tag}</span>
              ))}
            </div>
          ) : null}
        </div>
      </article>
    );
  }

  return (
    <article className="product-card">
      <Link className="product-image" href={`/products/${product.product_id}`}>
        <img src={productImage(product)} alt="" />
        {signals ? <span className="rank-badge">#{signals.final_rank}</span> : null}
      </Link>
      <button
        className={saved ? "favorite-button active" : "favorite-button"}
        type="button"
        aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`}
        title={saved ? "Remove saved product" : "Save product"}
        onClick={() => setSaved((current) => !current)}
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
