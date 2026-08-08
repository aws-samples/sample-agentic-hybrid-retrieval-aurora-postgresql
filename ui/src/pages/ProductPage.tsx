import {
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  GitCompareArrows,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useRoute } from "wouter";
import { api } from "../api";
import { MosaicMark } from "../components/MosaicMark";
import { ProductCard } from "../components/ProductCard";
import { ErrorState, LoadingState } from "../components/States";
import { productEditorialPoster, productImages } from "../media";
import type { ProductDetail, ProductSummary } from "../types";
import { showcaseProductDetail } from "../showcase";

type DetailTab = "overview" | "specs" | "reviews" | "evidence";

export function ProductPage() {
  const [, params] = useRoute("/products/:productId");
  const productId = params?.productId;
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [related, setRelated] = useState<ProductSummary[]>([]);
  const [selectedImage, setSelectedImage] = useState("");
  const [tab, setTab] = useState<DetailTab>("overview");
  const [comparing, setComparing] = useState(false);
  const id = Number(productId);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .product(id)
      .then(async (result) => {
        setProduct(result);
        setSelectedImage(productImages(result)[0]);
        try {
          const page = await api.catalog({ domain: result.domain }, 0, 5, "rating");
          setRelated(page.products.filter((item) => item.product_id !== result.product_id).slice(0, 4));
        } catch {
          setRelated([]);
        }
      })
      .catch((cause: Error) => {
        const localProduct = showcaseProductDetail(id);
        if (localProduct) {
          setProduct(localProduct);
          setSelectedImage(productImages(localProduct)[0]);
          setRelated([]);
          return;
        }
        setError(cause.message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(load, [load]);

  if (loading) return <div className="page"><LoadingState label="Loading product evidence" /></div>;
  if (error || !product) return <div className="page"><ErrorState message={error || "Product not found"} onRetry={load} /></div>;

  const gallery = Array.from(new Set([
    ...productImages(product),
    ...product.media.map((item) => item.image_url).filter((url) => url.startsWith("/")),
  ]));
  const attributes = Object.entries(product.attributes);
  const source = product.sources[0];
  const poster = productEditorialPoster(product);

  return (
    <div className="page product-page">
      <Link className="back-link" href="/catalog"><ArrowLeft size={16} /> Back to catalog</Link>
      <section className="product-hero">
        <div className="product-gallery">
          <div className="thumbnail-rail">
            {gallery.map((image, index) => (
              <button
                type="button"
                key={image}
                className={selectedImage === image ? "active" : ""}
                onClick={() => setSelectedImage(image)}
                aria-label={`View product image ${index + 1}`}
              >
                <img src={image} alt="" />
              </button>
            ))}
          </div>
          <div className="product-main-image">
            <img src={selectedImage || gallery[0]} alt="" />
          </div>
        </div>
        <div className="product-summary">
          <p className="product-breadcrumb">
            {product.domain.replaceAll("_", " ")} / {product.category} / {product.subcategory}
          </p>
          <h1>{product.title}</h1>
          <p className="product-model">{product.brand} / {product.model} / {product.sku}</p>
          <div className="rating-row prominent">
            {Array.from({ length: 5 }).map((_, index) => (
              <Star key={index} size={16} fill={index < Math.round(product.rating) ? "currentColor" : "none"} />
            ))}
            <strong>{product.rating.toFixed(1)}</strong>
            <span>{product.review_count.toLocaleString()} reviews</span>
          </div>
          <div className="product-price-row">
            <div className="product-price">${product.price_usd.toFixed(2)}</div>
            {product.list_price_usd > product.price_usd ? (
              <span>${product.list_price_usd.toFixed(2)}</span>
            ) : null}
          </div>
          <div className="availability-block">
            <p className={product.availability === "In Stock" ? "stock" : "muted"}>
              {product.availability === "In Stock" ? <Check size={16} /> : null}
              {product.availability}
            </p>
            <small>{product.inventory_count.toLocaleString()} units in the loaded catalog</small>
          </div>
          <p className="product-lede">{product.long_description}</p>
          <div className="product-primary-actions">
            <Link
              className="primary-button"
              href={`/search?mode=agent&q=${encodeURIComponent(`Compare ${product.title} with similar ${product.subcategory}`)}`}
            >
              <Sparkles size={17} /> Ask the agent
            </Link>
            <button
              type="button"
              className={comparing ? "secondary-button active" : "secondary-button"}
              onClick={() => setComparing((current) => !current)}
            >
              <GitCompareArrows size={17} />
              {comparing ? "Added to comparison" : "Add to comparison"}
            </button>
          </div>
          <div className="product-trust-row">
            <span><Database size={17} /><strong>Catalog source</strong><small>Inspectable row</small></span>
            <span><ShieldCheck size={17} /><strong>Attribution</strong><small>{source ? "Available" : "Unavailable"}</small></span>
            <span><Sparkles size={17} /><strong>Agent ready</strong><small>Citable evidence</small></span>
          </div>
        </div>
      </section>

      {poster ? (
        <section className="product-campaign" aria-label={`${product.model} editorial campaign`}>
          <figure className="product-campaign-poster">
            <img src={poster.src} alt={poster.alt} />
            <span className="poster-brand-repair" aria-label="Mosaic">
              <MosaicMark />
            </span>
          </figure>
          <div className="product-campaign-copy">
            <p className="eyebrow">Mosaic editorial</p>
            <h2>{product.model}</h2>
            <p>{product.short_description}</p>
          </div>
        </section>
      ) : null}

      <nav className="product-tabs" aria-label="Product information">
        {([
          ["overview", "Overview"],
          ["specs", "Specifications"],
          ["reviews", `Reviews (${product.reviews.length})`],
          ["evidence", "Source evidence"],
        ] as Array<[DetailTab, string]>).map(([value, label]) => (
          <button
            type="button"
            key={value}
            className={tab === value ? "active" : ""}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <section className="product-overview">
          <div className="product-rationale">
            <p className="eyebrow">Product overview</p>
            <h2>What stands out</h2>
            <p>{product.short_description}</p>
            <ul>
              {attributes.slice(0, 3).map(([key, value]) => (
                <li key={key}>
                  <Check size={16} />
                  <span>
                    <strong>{key.replaceAll("_", " ")}</strong>
                    {Array.isArray(value) ? value.join(", ") : String(value)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="matching-attributes">
            <p className="eyebrow">Structured metadata</p>
            <h2>Matching attributes</h2>
            <div className="attribute-chips">
              {attributes.slice(0, 8).map(([key, value]) => (
                <span key={key}>
                  {key.replaceAll("_", " ")}: {Array.isArray(value) ? value.join(", ") : String(value)}
                </span>
              ))}
            </div>
            <div className="evidence-readiness">
              <div>
                <Database size={20} />
                <span><strong>Evidence readiness</strong><small>{source ? "Source attribution available" : "Source attribution unavailable"}</small></span>
              </div>
              <p>
                Mosaic can retrieve this row, expose its ranking signals,
                and cite the source revision in an agent answer.
              </p>
            </div>
          </div>
          <div className="customer-highlights">
            <p className="eyebrow">Customer evidence</p>
            <h2>Review highlights</h2>
            {product.reviews.length ? product.reviews.slice(0, 3).map((review) => (
              <blockquote key={review.review_id}>
                <p>“{review.body}”</p>
                <cite>
                  {review.verified_purchase ? "Verified purchase" : "Catalog review"} / {review.rating}.0 stars
                </cite>
              </blockquote>
            )) : (
              <p className="muted">No review excerpts are loaded for this product.</p>
            )}
          </div>
        </section>
      ) : null}

      {tab === "specs" ? (
        <section className="tab-section">
          <p className="eyebrow">Structured product data</p>
          <h2>Specifications</h2>
          <dl className="spec-table">
            {attributes.map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {tab === "reviews" ? (
        <section className="tab-section">
          <p className="eyebrow">Customer evidence</p>
          <h2>Review excerpts</h2>
          <div className="review-list">
            {product.reviews.length ? product.reviews.map((review) => (
              <blockquote key={review.review_id}>
                <div className="rating-row"><Star size={14} fill="currentColor" /><strong>{review.rating}.0</strong></div>
                {review.title ? <strong>{review.title}</strong> : null}
                <p>{review.body}</p>
                <cite>{review.verified_purchase ? "Verified purchase" : "Catalog review"} / {review.review_date}</cite>
              </blockquote>
            )) : <p className="muted">No review evidence is loaded for this sample product.</p>}
          </div>
        </section>
      ) : null}

      {tab === "evidence" ? (
        <section className="tab-section">
          <p className="eyebrow">Source attribution</p>
          <h2>Inspectable catalog evidence</h2>
          <div className="source-box">
            <Database size={20} />
            <div>
              <strong>{source?.title ?? product.title}</strong>
              <span>{source?.source_uri ?? "No source URI available"}</span>
              <small>Revision {source?.revision ?? "unavailable"}</small>
              <p>{source?.quote ?? product.short_description}</p>
            </div>
          </div>
        </section>
      ) : null}

      {related.length ? (
        <section className="related-products">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Continue exploring</p>
              <h2>More in {product.domain.replaceAll("_", " ")}</h2>
            </div>
            <Link className="text-link" href={`/catalog?domain=${product.domain}`}>
              View catalog <ArrowRight size={16} />
            </Link>
          </div>
          <div className="product-grid">
            {related.map((item) => <ProductCard key={item.product_id} product={item} />)}
          </div>
        </section>
      ) : null}
    </div>
  );
}
