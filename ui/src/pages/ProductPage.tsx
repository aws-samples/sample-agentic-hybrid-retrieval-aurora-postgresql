import {
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  Heart,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Star,
  Truck,
} from "lucide-react";
import {
  CSSProperties,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useRoute } from "wouter";
import { api } from "../api";
import { cartQuantityLimit, useCommerce } from "../commerce";
import { MosaicMark } from "../components/MosaicMark";
import { ProductComplements } from "../components/ProductComplements";
import { catalogReturnPath } from "../navigation";
import { ProductCard } from "../components/ProductCard";
import { ErrorState, LoadingState } from "../components/States";
import { productFacts, formatAttributeLabel, formatAttributeValue, formatAvailability, formatPrice, isPurchasable, leafCategory } from "../format";
import { productEditorialPoster, productImageMap, productImages } from "../media";
import type { ProductDetail, ProductSummary } from "../types";

type DetailTab = "overview" | "specs" | "reviews" | "evidence";

export function ProductPage() {
  const { addItem, itemQuantity, isFavorite, toggleFavorite } = useCommerce();
  const [, params] = useRoute("/products/:productId");
  const productId = params?.productId;
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [related, setRelated] = useState<ProductSummary[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState("");
  const relatedImages = useMemo(() => productImageMap(related), [related]);
  const [selectedImage, setSelectedImage] = useState("");
  const [tab, setTab] = useState<DetailTab>("overview");
  const requestVersion = useRef(0);
  const relatedRequestVersion = useRef(0);
  const id = Number(productId);

  const loadRelated = useCallback((sourceProduct: ProductDetail) => {
    const version = relatedRequestVersion.current + 1;
    relatedRequestVersion.current = version;
    setRelatedLoading(true);
    setRelatedError("");
    api
      .similarProducts(sourceProduct.product_id)
      .then((products) => {
        if (version !== relatedRequestVersion.current) return;
        setRelated(
          products
            .filter((item) => item.product_id !== sourceProduct.product_id)
            .slice(0, 4),
        );
      })
      .catch((cause: unknown) => {
        if (version !== relatedRequestVersion.current) return;
        setRelated([]);
        setRelatedError(
          cause instanceof Error ? cause.message : "Related products are unavailable",
        );
      })
      .finally(() => {
        if (version === relatedRequestVersion.current) setRelatedLoading(false);
      });
  }, []);

  const load = useCallback(() => {
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    relatedRequestVersion.current += 1;
    setLoading(true);
    setError("");
    setRelated([]);
    setRelatedLoading(false);
    setRelatedError("");
    void (async () => {
      try {
        const result = await api.product(id);
        if (version !== requestVersion.current) return;
        setProduct(result);
        setSelectedImage(productImages(result)[0]);
        setTab("overview");
        setLoading(false);
        loadRelated(result);
      } catch (cause) {
        if (version !== requestVersion.current) return;
        setProduct(null);
        setRelated([]);
        setError(cause instanceof Error ? cause.message : "Product detail is unavailable");
      } finally {
        if (version === requestVersion.current) setLoading(false);
      }
    })();
  }, [id, loadRelated]);

  useEffect(() => {
    load();
    return () => {
      requestVersion.current += 1;
      relatedRequestVersion.current += 1;
    };
  }, [load]);

  if (loading) return <div className="page"><LoadingState label="Loading product evidence" /></div>;
  if (error || !product) return <div className="page"><ErrorState message={error || "Product not found"} onRetry={load} /></div>;

  const gallery = Array.from(new Set([
    ...productImages(product),
    ...product.media.map((item) => item.image_url).filter((url) => url.startsWith("/")),
  ]));
  const attributes = Object.entries(product.attributes);
  const source = product.sources[0];
  const poster = productEditorialPoster(product);
  const quantity = itemQuantity(product.product_id);
  const quantityLimit = cartQuantityLimit(product);
  const quantityAtLimit = quantity > 0 && quantity >= quantityLimit;
  const catalogReturnParams = new URLSearchParams({
    domain: product.domain,
    category_key: product.category_key,
  });
  const catalogReturnHref = catalogReturnPath(new URLSearchParams(window.location.search).get("from")) ?? `/catalog?${catalogReturnParams}`;
  const saved = isFavorite(product.product_id);
  const similarLabel = product.category_key.includes("monitors") ? "Similar monitors" : product.category_key.includes("headphones") ? "Similar headphones" : product.category_key.includes("chairs") ? "Similar chairs" : "Similar options";

  function moveTabFocus(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = Array.from(
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
        '[role="tab"]',
      ) ?? [],
    );
    const current = tabs.indexOf(event.currentTarget);
    if (current < 0 || !tabs.length) return;
    event.preventDefault();
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length)
          % tabs.length;
    tabs[next].focus();
    tabs[next].click();
  }

  return (
    <div className="page product-page">
      <Link
        className="back-link"
        href={catalogReturnHref}
      >
        <ArrowLeft size={16} /> Back to catalog
      </Link>
      <section className="product-hero">
        <div className="product-gallery">
          {/* A rail with one thumbnail is a control that cannot do anything, so
              it only renders when there is a second image to switch to. */}
          {gallery.length > 1 ? (
            <div className="thumbnail-rail">
              {gallery.map((image, index) => (
                <button
                  type="button"
                  key={image}
                  className={selectedImage === image ? "active" : ""}
                  onClick={() => setSelectedImage(image)}
                  aria-label={`View product image ${index + 1}`}
                  aria-pressed={selectedImage === image}
                >
                  <img src={image} alt="" />
                </button>
              ))}
            </div>
          ) : null}
          <div className="product-main-image">
            <img src={selectedImage || gallery[0]} alt={product.title} />
          </div>
        </div>
        <div className="product-summary">
          <p className="product-breadcrumb">
            {product.category_path}
          </p>
          <h1>{product.title}</h1>
          <p className="product-lede">{product.long_description}</p>
          {/* A rating with no reviews behind it is not evidence, so the stars
              only appear once the catalog actually carries review counts. */}
          {product.review_count && product.rating !== null ? (
            <div className="rating-row prominent">
              {Array.from({ length: 5 }).map((_, index) => (
                <Star key={index} size={16} fill={index < Math.round(product.rating ?? 0) ? "currentColor" : "none"} />
              ))}
              <strong>{product.rating.toFixed(1)}</strong>
              <span>{product.review_count.toLocaleString()} reviews</span>
            </div>
          ) : null}

          <div className="product-buy-row">
            <div className="product-price-row">
              <div className="product-price">{formatPrice(product.price_cents, product.currency)}</div>
              {product.list_price_cents > product.price_cents ? (
                <span>{formatPrice(product.list_price_cents, product.currency)}</span>
              ) : null}
            </div>
            <div className="availability-block">
              <p className={isPurchasable(product.availability) ? "stock" : "muted"}>
                {isPurchasable(product.availability) ? <Check size={15} /> : null}
                {formatAvailability(product.availability)}
              </p>
              <small>
                {product.inventory_count === 1
                  ? "1 unit in the loaded catalog"
                  : `${product.inventory_count.toLocaleString()} units in the loaded catalog`}
              </small>
            </div>
          </div>

          <div className="product-cta-stack">
            <button
              className="product-cta-primary"
              type="button"
              disabled={!quantityLimit || quantityAtLimit}
              onClick={() => addItem(product)}
            >
              <ShoppingBag size={17} />
              {!quantityLimit
                ? formatAvailability(product.availability)
                : quantityAtLimit
                  ? `Maximum in cart (${quantity})`
                  : quantity
                    ? `Add another (${quantity} in cart)`
                    : "Add to cart"}
            </button>
            <Link
              className="product-cta-secondary"
              href={`/catalog?ask=1&q=${encodeURIComponent(`Compare ${product.title} with other ${leafCategory(product.category_path)} options. Keep the current product in the comparison and explain the trade-offs.`)}`}
            >
              <Sparkles size={16} /> Compare in Ask Mosaic
            </Link>
          </div>

          <button type="button" className="product-save-button" aria-label={saved ? `Remove ${product.title} from saved products` : `Save ${product.title}`} aria-pressed={saved} onClick={() => toggleFavorite(product.product_id)}>
            <Heart size={17} fill={saved ? "currentColor" : "none"} /> {saved ? "Saved to your shortlist" : "Save to your shortlist"}
          </button>
          {product.warranty_months != null || product.shipping_days != null ? (
            <div className="product-assurances">
              {product.warranty_months != null ? <span><ShieldCheck size={19} /><small>{product.warranty_months ? `${product.warranty_months}-month warranty` : "No warranty listed"}</small></span> : null}
              {product.shipping_days != null ? <span><Truck size={19} /><small>{product.shipping_days ? `Ships in ${product.shipping_days} days` : "Same-day shipping"}</small></span> : null}
            </div>
          ) : null}
        </div>
      </section>

      {/* Evidence row. Every panel states what the catalog actually holds; the
          reference board's confidence dial is driven by the rating and review
          count rather than an invented score. */}
      <section className="product-evidence-row" aria-label="Product facts and sources">
        <article>
          <header><Sparkles size={15} /><h3>About this product</h3></header>
          <p>{product.short_description}</p>
        </article>
        <article>
          <header><Check size={15} /><h3>Product details</h3></header>
          <dl className="product-key-facts">
            {productFacts(product.attributes).map(({ key, label, value }) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </article>
        <article>
          <header><Database size={15} /><h3>Source evidence</h3></header>
          <p>
            Inspect this product's source records and revisions. A catalog page
            alone does not explain how a search ranked it.
          </p>
          <button className="text-link product-source-link" type="button" onClick={() => {
            setTab("evidence");
            document.getElementById("product-tab-evidence")?.focus({ preventScroll: true });
            document.getElementById("product-information")?.scrollIntoView({ block: "start" });
          }}>
            Inspect source records <ArrowRight size={15} aria-hidden="true" />
          </button>
        </article>
        {/* The reference board shows a "confidence score" dial. There is no such
            column in the catalog, so this panel reports the rating the row does
            carry, and says so plainly when no reviews back it. */}
        <article className="product-confidence">
          <header><ShieldCheck size={15} /><h3>Customer rating</h3></header>
          {product.review_count && product.rating !== null ? (
            <div>
              <span
                className="product-dial"
                style={{
                  ...({ "--sweep": `${(product.rating / 5) * 100}%` } as CSSProperties),
                }}
              >
                <b>{product.rating.toFixed(1)}</b>
              </span>
              <small>Across {product.review_count.toLocaleString()} catalog reviews</small>
            </div>
          ) : (
            <p>
              No reviews are loaded for this row, so no rating is shown. Load the
              full catalog to populate review evidence.
            </p>
          )}
        </article>
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

      <nav id="product-information" className="product-tabs" aria-label="Product information" role="tablist">
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
            onKeyDown={moveTabFocus}
            aria-controls={`product-panel-${value}`}
            aria-selected={tab === value}
            id={`product-tab-${value}`}
            role="tab"
            tabIndex={tab === value ? 0 : -1}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <section
          aria-labelledby="product-tab-overview"
          className="product-overview"
          id="product-panel-overview"
          role="tabpanel"
        >
          <div className="product-rationale">
            <p className="eyebrow">Structured metadata</p>
            <h2>Full attribute set</h2>
            <dl className="spec-table">
              {attributes.map(([key, value]) => (
                <div key={key}>
                  <dt>{formatAttributeLabel(key)}</dt>
                  <dd>{formatAttributeValue(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="customer-highlights">
            <p className="eyebrow">Catalog record</p>
            <h2>Where this row comes from</h2>
            <dl className="spec-table">
              <div>
                <dt>Source system</dt>
                <dd>{product.source_system}</dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>{source?.revision ?? "unavailable"}</dd>
              </div>
              <div>
                <dt>SKU</dt>
                <dd>{product.sku}</dd>
              </div>
              <div>
                <dt>Brand / model</dt>
                <dd>{product.brand} / {product.model}</dd>
              </div>
            </dl>
            {product.reviews.length ? (
              <blockquote>
                <p>“{product.reviews[0].body}”</p>
                <cite>
                  {product.reviews[0].source_name}
                  {product.reviews[0].verified_purchase ? " · Verified purchase" : ""}
                  {product.reviews[0].rating !== null
                    ? ` / ${product.reviews[0].rating.toFixed(1)} stars`
                    : ""}
                </cite>
              </blockquote>
            ) : null}
          </div>
        </section>
      ) : null}

      {tab === "specs" ? (
        <section
          aria-labelledby="product-tab-specs"
          className="tab-section"
          id="product-panel-specs"
          role="tabpanel"
        >
          <p className="eyebrow">Structured product data</p>
          <h2>Specifications</h2>
          <dl className="spec-table">
            {attributes.map(([key, value]) => (
              <div key={key}>
                <dt>{formatAttributeLabel(key)}</dt>
                <dd>{formatAttributeValue(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {tab === "reviews" ? (
        <section
          aria-labelledby="product-tab-reviews"
          className="tab-section"
          id="product-panel-reviews"
          role="tabpanel"
        >
          <p className="eyebrow">Customer evidence</p>
          <h2>Review excerpts</h2>
          <div className="review-list">
            {product.reviews.length ? product.reviews.map((review) => (
              <blockquote key={review.review_id}>
                {review.rating !== null ? (
                  <div className="rating-row">
                    {Array.from({ length: 5 }).map((_, index) => (
                      <Star
                        key={index}
                        size={13}
                        fill={index < Math.round(review.rating ?? 0) ? "currentColor" : "none"}
                      />
                    ))}
                    <strong>{review.rating.toFixed(1)}</strong>
                  </div>
                ) : null}
                {review.title ? <strong>{review.title}</strong> : null}
                <p>{review.body}</p>
                <cite>
                  {review.source_name}
                  {review.verified_purchase ? " · Verified purchase" : ""}
                  {review.review_date ? ` / ${review.review_date}` : ""}
                </cite>
              </blockquote>
            )) : <p className="muted">No review evidence is loaded for this sample product.</p>}
          </div>
        </section>
      ) : null}

      {tab === "evidence" ? (
        <section
          aria-labelledby="product-tab-evidence"
          className="tab-section"
          id="product-panel-evidence"
          role="tabpanel"
        >
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

      <ProductComplements categoryKey={product.category_key} />

      {relatedLoading ? (
        <section className="related-products" aria-label="Related products">
          <LoadingState label="Loading related products" />
        </section>
      ) : relatedError ? (
        <section className="related-products" aria-label="Related products">
          <ErrorState
            message={relatedError}
            onRetry={() => loadRelated(product)}
          />
        </section>
      ) : related.length ? (
        <section className="related-products">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Continue exploring</p>
              <h2>{similarLabel}</h2>
            </div>
            <Link className="text-link" href={`/catalog?domain=${product.domain}&category_key=${product.category_key}`}>
              View all <ArrowRight size={16} />
            </Link>
          </div>
          <div className="product-grid related-grid">
            {related.map((item) => (
              <ProductCard
                key={item.product_id}
                product={item}
                imageSrc={relatedImages.get(item.product_id)}
                variant="catalog"
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
