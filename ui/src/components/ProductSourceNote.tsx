import { ExternalLink } from "lucide-react";
import { formatPrice } from "../format";
import type { ProductSummary } from "../types";

export function ProductSourceNote({ product }: { product: ProductSummary }) {
  if (!product.source_dataset || !product.listing_url) return null;
  return <aside className="product-source-note" aria-label="About this listing">
    <a href={product.listing_url} target="_blank" rel="noreferrer">View original listing <ExternalLink size={14} /></a>
    <p>Original photos and product details from Amazon Reviews 2023. Ratings reflect that dataset; prices, availability and variants may have changed.</p>
    {product.historical_price_cents != null ? <small>Price in the source: {formatPrice(product.historical_price_cents, product.currency)}. Check the listing for today’s price.</small> : null}
    {product.historical_price_min_cents != null ? <small>Source price started at {formatPrice(product.historical_price_min_cents, product.currency)}. This is not a current offer.</small> : null}
  </aside>;
}
