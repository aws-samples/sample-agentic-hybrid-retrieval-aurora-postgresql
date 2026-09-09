import { Star } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { formatAvailability, formatCategoryKey, formatPrice } from "../format";
import { productImage } from "../media";
import type { ProductSummary } from "../types";
import "../result-product-card.css";

/** One catalog identity and its actual facts, shared by answers and ranking previews. */
export function ResultProductCard({ product, imageSrc, rank, footer, onSelect, onHighlight }: {
  product: ProductSummary; imageSrc?: string; rank?: number; footer?: ReactNode;
  onSelect?: (productId: number) => void; onHighlight?: (productId: number | null) => void;
}) {
  const content = <>
    <span className="result-product-media"><img src={imageSrc || productImage(product)} alt="" width={480} height={480} loading="lazy" decoding="async" />{rank != null && <span className="result-product-position" aria-label={`Recommendation ${rank}`}>{String(rank).padStart(2, "0")}</span>}</span>
    <span className="result-product-copy"><span className="result-product-category">{formatCategoryKey(product.category_key)}</span><strong className="result-product-name">{product.title}</strong><span className="result-product-rating" aria-label={product.rating != null ? `${product.rating.toFixed(1)} out of 5 from ${product.review_count} reviews` : "No ratings yet"}><Star size={14} aria-hidden="true" />{product.rating != null ? <><strong>{product.rating.toFixed(1)}</strong><span>({product.review_count.toLocaleString()})</span></> : <span>No ratings yet</span>}</span><span className="result-product-price">{formatPrice(product.price_cents, product.currency)}</span><span className="result-product-stock">{formatAvailability(product.availability)}</span></span>
  </>;
  return <article className="result-product-card" data-product-id={product.product_id}
    onMouseEnter={() => onHighlight?.(product.product_id)} onMouseLeave={() => onHighlight?.(null)}
    onFocusCapture={() => onHighlight?.(product.product_id)} onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onHighlight?.(null); }}>
    {onSelect ? <button type="button" className="result-product-main" onClick={() => onSelect(product.product_id)}>{content}</button> : <Link href={`/products/${product.product_id}`} className="result-product-main">{content}</Link>}
    {footer && <div className="result-product-footer">{footer}</div>}
  </article>;
}
