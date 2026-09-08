import { useEffect, useState } from "react";
import workspaceCollection from "../../../data/media/workspace_collection.json";
import { api } from "../api";
import { cachedRequest } from "../cachedRequest";
import { productImageMap } from "../media";
import type { ProductSummary } from "../types";
import { ProductCard } from "./ProductCard";
import "../workspace-continuation.css";

const supportingProducts = workspaceCollection.supporting_product_ids.map(productId =>
  cachedRequest(async () => {
    const product = await api.product(productId);
    if (product.product_id !== productId) throw new Error("Product identity did not match the requested workspace piece.");
    return product;
  }),
);

/** This edit is a browse collection, not a compatibility or similarity claim. */
export function ContinueWorkspace() {
  const [products, setProducts] = useState<ProductSummary[]>([]);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setPending(true);
    setFailed(false);
    void Promise.allSettled(supportingProducts.map(request => request.load())).then(results => {
      if (!active) return;
      setProducts(results.flatMap(result => result.status === "fulfilled" ? [result.value] : []));
      setFailed(results.some(result => result.status === "rejected"));
      setPending(false);
    });
    return () => { active = false; };
  }, [retry]);

  const images = productImageMap(products);
  return (
    <section className="workspace-continuation" aria-labelledby="workspace-continuation-title" aria-busy={pending}>
      <header>
        <h2 id="workspace-continuation-title">Continue the workspace.</h2>
        <p>Light for the desk, connections for the day, and a better place for his laptop.</p>
      </header>
      {products.length ? <div className="workspace-continuation-grid">
        {products.map(product => <ProductCard key={product.product_id} product={product} imageSrc={images.get(product.product_id)} variant="catalog" />)}
      </div> : pending ? <p className="workspace-continuation-status" role="status">Loading the supporting pieces…</p> : null}
      {failed ? <div className="workspace-continuation-status" role="status">
        <p>Some workspace pieces couldn’t load.</p>
        <button type="button" onClick={() => setRetry(value => value + 1)}>Try again</button>
      </div> : null}
    </section>
  );
}
