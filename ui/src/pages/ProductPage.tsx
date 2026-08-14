import {
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  RotateCcw,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Star,
  Truck,
} from "lucide-react";
import {
  CSSProperties,
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
import { ProductCard } from "../components/ProductCard";
import { ErrorState, LoadingState } from "../components/States";
import { formatAvailability, formatPrice, isPurchasable, leafCategory } from "../format";
import { productEditorialPoster, productImageMap, productImages } from "../media";
import type { ProductDetail, ProductSummary } from "../types";

type DetailTab = "overview" | "specs" | "reviews" | "evidence";

export function ProductPage() {
  const { addItem, itemQuantity } = useCommerce();
  const [, params] = useRoute("/products/:productId");
  const productId = params?.productId;
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [related, setRelated] = useState<ProductSummary[]>([]);
  const relatedImages = useMemo(() => productImageMap(related), [related]);
  const [selectedImage, setSelectedImage] = useState("");
  const [tab, setTab] = useState<DetailTab>("overview");
  const requestVersion = useRef(0);
  const id = Number(productId);

  const load = useCallback(() => {
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        const result = await api.product(id);
        if (version !== requestVersion.current) return;
        setProduct(result);
        setSelectedImage(productImages(result)[0]);
        try {
          const page = await api.catalog({ domain: result.domain }, 0, 5, "rating");
          if (version !== requestVersion.current) return;
          setRelated(page.products.filter((item) => item.product_id !== result.product_id).slice(0, 4));
        } catch {
          if (version !== requestVersion.current) return;
          setRelated([]);
        }
      } catch (cause) {
        if (version !== requestVersion.current) return;
        setProduct(null);
        setRelated([]);
        setError(cause instanceof Error ? cause.message : "Product detail is unavailable");
      } finally {
        if (version === requestVersion.current) setLoading(false);
      }
    })();
  }, [id]);

  useEffect(() => {
    load();
    return () => {
      requestVersion.current += 1;
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

  return (
    <div className="page product-page">
      <Link className="back-link" href="/catalog"><ArrowLeft size={16} /> Back to catalog</Link>
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
                >
                  <img src={image} alt="" />
                </button>
              ))}
            </div>
          ) : null}
          <div className="product-main-image">
            <img src={selectedImage || gallery[0]} alt="" />
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

          <div className="product-assurances">
            <span><RotateCcw size={19} /><small>60-day free returns</small></span>
            <span><ShieldCheck size={19} /><small>2-year warranty</small></span>
            <span><Truck size={19} /><small>Free shipping over $75</small></span>
          </div>
        </div>
      </section>

      {/* Evidence row. Every panel states what the catalog actually holds; the
          reference board's confidence dial is driven by the rating and review
          count rather than an invented score. */}
      <section className="product-evidence-row" aria-label="Why Mosaic surfaces this product">
        <article>
          <header><Sparkles size={17} /><h3>Why Mosaic recommends this</h3></header>
          <p>{product.short_description}</p>
        </article>
        <article>
          <header><Check size={17} /><h3>Matching attributes</h3></header>
          <ul>
            {attributes.slice(0, 4).map(([key, value]) => (
              <li key={key}>
                <Check size={14} />
                <span>{Array.isArray(value) ? value.join(", ") : String(value)}</span>
              </li>
            ))}
          </ul>
        </article>
        <article>
          <header><Database size={17} /><h3>Evidence &amp; retrieval</h3></header>
          <p>
            Selected by hybrid retrieval over the loaded catalog using lexical,
            trigram, and vector signals.
          </p>
          <Link className="text-link" href="/labs/retrieval">
            See how ranking works <ArrowRight size={15} />
          </Link>
        </article>
        {/* The reference board shows a "confidence score" dial. There is no such
            column in the catalog, so this panel reports the rating the row does
            carry, and says so plainly when no reviews back it. */}
        <article className="product-confidence">
          <header><ShieldCheck size={17} /><h3>Customer rating</h3></header>
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
            <p className="eyebrow">Structured metadata</p>
            <h2>Full attribute set</h2>
            <dl className="spec-table">
              {attributes.map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
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
                  {" / "}
                  {product.reviews[0].rating}.0 stars
                </cite>
              </blockquote>
            ) : null}
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
                {review.rating !== null ? (
                  <div className="rating-row"><Star size={14} fill="currentColor" /><strong>{review.rating.toFixed(1)}</strong></div>
                ) : null}
                {review.title ? <strong>{review.title}</strong> : null}
                <p>{review.body}</p>
                <cite>
                  {review.source_name}
                  {review.verified_purchase ? " · Verified purchase" : ""}
                  {" / "}
                  {review.review_date}
                </cite>
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
              <h2>You may also like</h2>
            </div>
            <Link className="text-link" href={`/catalog?domain=${product.domain}`}>
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
