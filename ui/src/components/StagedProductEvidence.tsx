import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";

type SourceEvidence = {
  evidence_id: string;
  parent_asin: string;
  variant_asin: string | null;
  evidence_type: "product_spec" | "customer_review";
  title: string;
  text: string;
  source_date: string | null;
  verified_purchase: boolean | null;
  rating: number | null;
  helpful_votes?: number;
};
type SourceInspection = {
  product: { parent_asin: string; historical_price_cents: number | null; historical_price_min_cents?: number | null; current_price_cents: null; availability: null };
  evidence: SourceEvidence[];
  review_coverage: { complete_source_scan: boolean; selection_policy: string }[];
};

export function StagedProductEvidence({ productId }: { productId: string }) {
  const [data, setData] = useState<SourceInspection | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setData(null);
    void fetch(`/api/catalog-staging/products/${encodeURIComponent(productId)}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404
          ? "Source inspection is not available for this product yet."
          : "The source records could not be loaded from Aurora.");
        const value = await response.json() as SourceInspection;
        if (value.product?.parent_asin !== productId || !Array.isArray(value.evidence)
          || !Array.isArray(value.review_coverage)
          || value.evidence.some((record) => record.parent_asin !== productId
            || typeof record.evidence_id !== "string" || typeof record.text !== "string")) {
          throw new Error("The source response does not match this product.");
        }
        if (!controller.signal.aborted) setData(value);
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Source inspection failed.");
      });
    return () => controller.abort();
  }, [productId, attempt]);
  if (error) return <div className="catalog-preview-evidence"><p role="alert">{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry source inspection</button></div>;
  if (!data) return <p role="status">Loading source records from Aurora…</p>;
  const reviews = data.evidence.filter(record => record.evidence_type === "customer_review");
  const spec = data.evidence.find(record => record.evidence_type === "product_spec");
  const sourceLink = (record: SourceEvidence) => `/api/catalog-staging/products/${encodeURIComponent(productId)}/evidence/${encodeURIComponent(record.evidence_id)}`;
  const price = data.product.historical_price_cents;
  const startingPrice = data.product.historical_price_min_cents;
  const formatPrice = (amount: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount / 100);
  return <section className="catalog-preview-evidence" aria-label="Evidence from Aurora">
    <h3>Evidence from Aurora</h3>
    <p>{price !== null ? `Historical listing price: ${formatPrice(price)}.` : startingPrice != null ? `Historical listing price: from ${formatPrice(startingPrice)}. The source does not report an exact price.` : "No price reported in the dataset."} Current price and availability are unknown.</p>
    {spec ? <a href={sourceLink(spec)} target="_blank" rel="noreferrer">Inspect the product source <ExternalLink size={14} /></a> : null}
    <h3>Customer experiences</h3>
    <p>{reviews.length ? `${reviews.length} selected ${reviews.length === 1 ? "review" : "reviews"} from the source dataset.` : "No review text has been imported for this product in the current sample."} These samples do not represent all customers or determine the product’s overall rating.</p>
    {reviews.map(record => <details className="catalog-preview-review" key={record.evidence_id}>
      <summary><span>{record.rating} / 5 · {record.title || "Customer review"}</span></summary>
      <p className="catalog-preview-review-meta">{record.source_date} · {record.verified_purchase ? "Verified purchase in source" : "Purchase not verified in source"} · {record.helpful_votes ?? 0} helpful votes</p>
      <p className="catalog-preview-original">{record.text.replace(/<br\s*\/?\s*>/gi, "\n")}</p>
      <p>Reviewed variant: {record.variant_asin}. This experience does not establish another variant’s specifications.</p>
      <a href={sourceLink(record)} target="_blank" rel="noreferrer">Inspect this review’s source <ExternalLink size={14} /></a>
    </details>)}
    {data.review_coverage.length ? <details className="catalog-preview-review"><summary>How these reviews were selected</summary><p>{data.review_coverage[0].selection_policy}</p>{data.review_coverage.some(sample => !sample.complete_source_scan) ? <p>The source scan is partial. Missing coverage does not mean no reviews exist.</p> : null}</details> : null}
  </section>;
}
