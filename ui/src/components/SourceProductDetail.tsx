import { ArrowLeft, ArrowRight, ChevronDown, ExternalLink, Heart, Sparkles, Star } from "lucide-react";
import { useState } from "react";
import { Link } from "wouter";
import { useCommerce } from "../commerce";
import { formatAttributeLabel, formatAttributeValue, formatPrice, leafCategory } from "../format";
import { productImage } from "../media";
import type { ProductDetail, ProductSummary } from "../types";
import { ProductCard } from "./ProductCard";
import { ErrorState, LoadingState } from "./States";

function ExpandableText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const displayText = text.replace(/<br\s*\/?\s*>/gi, "\n");
  return (
    <div className="source-expandable-text">
      <p className={!expanded && text.length > 320 ? "source-text-preview" : ""}>{displayText}</p>
      {text.length > 320 ? (
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show less" : "Read full text"}
        </button>
      ) : null}
    </div>
  );
}

/** Original listing content is available in full without overwhelming the first view. */
export function SourceProductDetail({
  product, catalogReturnHref, related, relatedLoading, relatedError, onRetryRelated,
}: {
  product: ProductDetail;
  catalogReturnHref: string;
  related: ProductSummary[];
  relatedLoading: boolean;
  relatedError: string;
  onRetryRelated: () => void;
}) {
  const { isFavorite, toggleFavorite } = useCommerce();
  const gallery = Array.from(new Set([
    productImage(product),
    ...product.media.map((item) => item.image_url).filter((url) => url.startsWith("https://")),
  ]));
  const [selectedImage, setSelectedImage] = useState(gallery[0]);
  const [fullTitle, setFullTitle] = useState(false);
  const saved = isFavorite(product.product_id);
  const attributes = Object.entries(product.attributes);
  const facts = attributes.filter(([key, value]) => (
    !["brand", "manufacturer", "best sellers rank", "date first available"].includes(key.toLowerCase())
    && value != null && typeof value !== "object" && String(value).length < 100
  )).slice(0, 4);
  const features = product.source_features ?? [];
  const source = product.sources[0];
  const category = leafCategory(product.category_path);

  return (
    <div className="page source-product-page">
      <Link className="back-link" href={catalogReturnHref}><ArrowLeft size={16} /> Back to catalog</Link>
      <section className="source-detail-hero" aria-label="Product summary">
        <div className="source-detail-gallery">
          <div className="source-detail-photo">
            <img src={selectedImage} alt={product.title} />
            <button className="source-save-photo" type="button" aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`} aria-pressed={saved} onClick={() => toggleFavorite(product.product_id)}>
              <Heart size={20} fill={saved ? "currentColor" : "none"} />
            </button>
          </div>
          {gallery.length > 1 ? (
            <div className="source-detail-thumbnails" aria-label="Product photos">
              {gallery.map((image, index) => (
                <button key={image} type="button" aria-label={`View product image ${index + 1}`} aria-pressed={image === selectedImage} onClick={() => setSelectedImage(image)}>
                  <img src={image} alt="" loading="lazy" />
                </button>
              ))}
            </div>
          ) : null}
          <p className="source-photo-caption">Original listing photos{gallery.length > 1 ? ` · ${gallery.length} views` : ""}</p>
        </div>

        <div className="source-detail-summary">
          <p className="source-detail-category">{product.brand ? `${product.brand} · ` : ""}{category}</p>
          <h1 id="source-product-title" className={!fullTitle && product.title.length > 115 ? "source-title-preview" : ""}>{product.title}</h1>
          {product.title.length > 115 ? (
            <button className="source-expand-title" type="button" aria-expanded={fullTitle} aria-controls="source-product-title" onClick={() => setFullTitle(!fullTitle)}>
              {fullTitle ? "Show less" : "Show full product name"}
            </button>
          ) : null}
          {product.rating != null && product.review_count ? (
            <p className="source-detail-rating"><Star size={16} fill="currentColor" /><strong>{product.rating.toFixed(1)}</strong><span>{product.review_count.toLocaleString()} historical ratings</span></p>
          ) : null}
          {features.length ? (
            <ul className="source-feature-preview">
              {features.slice(0, 3).map((feature, index) => <li key={index}>{feature}</li>)}
            </ul>
          ) : null}
          {facts.length ? (
            <dl className="source-detail-facts">
              {facts.map(([key, value]) => <div key={key}><dt>{formatAttributeLabel(key)}</dt><dd>{formatAttributeValue(value, key)}</dd></div>)}
            </dl>
          ) : null}
          <div className="source-detail-actions">
            <a className="product-cta-primary" href={product.listing_url ?? undefined} target="_blank" rel="noreferrer">View original listing <ExternalLink size={16} /></a>
            <Link className="product-cta-secondary" href={`/catalog?ask=1&q=${encodeURIComponent(`Compare listing ${product.sku} with similar ${category} options. Keep this listing in the comparison and explain the trade-offs.`)}`}><Sparkles size={16} /> Compare in Ask Mosaic</Link>
          </div>
          <p className="source-detail-note">Original details from Amazon Reviews 2023. Check the listing for today’s price, availability and variants.</p>
        </div>
      </section>

      <section className="source-detail-information" aria-label="Product information">
        <details>
          <summary><span>Description &amp; features</span><ChevronDown size={18} /></summary>
          <div className="source-detail-content">
            {features.length ? <ul className="source-feature-list">{features.map((feature, index) => <li key={index}>{feature}</li>)}</ul> : null}
            {product.long_description ? <ExpandableText text={product.long_description} /> : null}
            {!features.length && !product.long_description ? <p>No description was included in this listing.</p> : null}
          </div>
        </details>
        <details>
          <summary><span>Specifications</span><ChevronDown size={18} /></summary>
          <div className="source-detail-content">
            {attributes.length ? <dl className="source-specifications">{attributes.map(([key, value]) => <div key={key}><dt>{formatAttributeLabel(key)}</dt><dd>{formatAttributeValue(value, key)}</dd></div>)}</dl> : <p>No specifications were included in this listing.</p>}
          </div>
        </details>
        <details>
          <summary><span>Customer reviews <small>{product.reviews.length ? `${product.reviews.length} shown${product.review_count ? ` of ${product.review_count.toLocaleString()} ${product.review_count === 1 ? "rating" : "ratings"}` : ""}` : "None imported"}</small></span><ChevronDown size={18} /></summary>
          <div className="source-detail-content">
            <p className="source-review-note">{product.reviews.length ? "Selected historical reviews, chosen for helpfulness within positive, mixed and critical ratings. They are not a representative sample of the ratings above, and may refer to different variants of the same listing." : "No review text was imported for this listing. Any rating shown above comes from the original listing."}</p>
            <div className="source-detail-reviews">
              {product.reviews.map((review) => (
                <article key={review.review_id}>
                  <div className="source-review-heading">
                    {review.rating != null ? <span><Star size={14} fill="currentColor" /> {review.rating.toFixed(1)}</span> : null}
                    {review.title ? <h3>{review.title}</h3> : null}
                  </div>
                  <ExpandableText text={review.body} />
                  <p className="source-review-byline">{review.source_name}{review.verified_purchase ? " · Verified purchase" : ""}{review.review_date ? ` · ${review.review_date}` : ""}</p>
                </article>
              ))}
            </div>
          </div>
        </details>
        <details>
          <summary><span>About this listing</span><ChevronDown size={18} /></summary>
          <div className="source-detail-content">
            <p>The photos, wording, specifications and ratings are preserved from the source dataset. Product details may have changed since they were collected.</p>
            <dl className="source-specifications">
              <div><dt>Source</dt><dd>{product.source_system}</dd></div>
              <div><dt>Listing ID</dt><dd>{product.sku}</dd></div>
              {product.model ? <div><dt>Model</dt><dd>{product.model}</dd></div> : null}
              {product.historical_price_cents != null ? <div><dt>Price in the source</dt><dd>{formatPrice(product.historical_price_cents, product.currency)} · Not a current offer</dd></div> : null}
              {product.historical_price_min_cents != null ? <div><dt>Starting price in the source</dt><dd>{formatPrice(product.historical_price_min_cents, product.currency)} · Not a current offer</dd></div> : null}
              {product.historical_price_cents == null && product.historical_price_min_cents == null ? <div><dt>Price in the source</dt><dd>Not reported: unknown, not free</dd></div> : null}
              {source?.revision ? <div><dt>Saved version</dt><dd><code>{source.revision}</code></dd></div> : null}
            </dl>
          </div>
        </details>
      </section>

      {relatedLoading ? <section className="source-related-products" aria-label="Related products"><LoadingState label="Loading related products" /></section>
        : relatedError ? <section className="source-related-products" aria-label="Related products"><ErrorState message={relatedError} onRetry={onRetryRelated} /></section>
          : related.length ? (
            <section className="source-related-products">
              <div className="section-heading"><h2>Similar options</h2><Link className="text-link" href={`/catalog?domain=${product.domain}&category_key=${product.category_key}`}>View all <ArrowRight size={16} /></Link></div>
              <div className="product-grid">{related.map((item) => <ProductCard key={item.product_id} product={item} variant="catalog" />)}</div>
            </section>
          ) : null}
    </div>
  );
}
