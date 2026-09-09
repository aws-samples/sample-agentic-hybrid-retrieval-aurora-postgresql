import type { CSSProperties, ReactNode } from "react";
import { Link } from "wouter";
import { formatCategoryKey, formatPriceCompact } from "../format";
import { productImageMap } from "../media";
import type { AgentCitation, ProductSummary } from "../types";
import "../reason-products.css";

/** Keep product photography attached to the records the agent actually returned. */
export function ReasonProducts({ products, citations = [], title, description, renderSearchLink, ordered = false }: {
  products: ProductSummary[]; citations?: AgentCitation[]; title: string; description?: string;
  ordered?: boolean;
  renderSearchLink?: (product: ProductSummary) => ReactNode;
}) {
  const images = productImageMap(products);
  const List = ordered ? "ol" : "ul";
  if (!products.length) return null;
  return <section className="reason-products" aria-label={title}>
    <header><h3>{title}</h3>{description ? <p>{description}</p> : null}</header>
    <List>
      {products.map((product, index) => {
        const sources = new Set(citations.filter((citation) => citation.product_id === product.product_id).map((citation) => citation.evidence_id)).size;
        return <li key={product.product_id} style={{ "--product-reveal-delay": `${Math.min(index, 4) * 60}ms` } as CSSProperties}>
          <Link href={`/products/${product.product_id}`} className="reason-product-link">
            <div className="reason-product-photo"><img src={images.get(product.product_id)} alt="" width={1200} height={800} loading="lazy" decoding="async" /></div>
            <div className="reason-product-copy"><strong>{product.title}</strong><span>{formatCategoryKey(product.category_key)}</span></div>
          </Link>
          <div className="reason-product-meta"><strong>{formatPriceCompact(product.price_cents, product.currency)}</strong>{sources ? <span>{sources} cited {sources === 1 ? "source" : "sources"}</span> : null}</div>
          {renderSearchLink?.(product)}
        </li>;
      })}
    </List>
  </section>;
}
