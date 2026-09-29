import { ArrowUpRight } from "lucide-react";
import { Link } from "wouter";
import { armLanguage } from "../../retrievalLanguage";
import type { ProductSummary } from "../../types";
import { pickName } from "../ask-mosaic/comparison";

/** "Found by exact terms and meaning match", from the arms that ranked it. */
export function foundBySentence(product: ProductSummary): string | null {
  const signals = product.signals;
  if (!signals) return null;
  const arms = armLanguage.filter((arm) => signals[arm.key].rank != null).map((arm) => arm.label.toLowerCase());
  if (!arms.length) return null;
  if (arms.length === 1) return `Found by ${arms[0]} only`;
  return `Found by ${arms.slice(0, -1).join(", ")} and ${arms[arms.length - 1]}`;
}

/** Whether the agent's answer picked the search's first result, when there is an answer. */
export type AgentVerdict = "picked" | "not-picked" | "declined" | null;

const VERDICT: Record<Exclude<AgentVerdict, null>, string> = {
  picked: "One of the agent’s picks.",
  "not-picked": "Not among the agent’s picks.",
  declined: "Not recommended: the agent’s sources did not support a choice.",
};
const rank = (value: number | null | undefined) => (value == null ? null : `#${value}`);

/**
 * The search's first result on its own plate: what a shopper would see first,
 * with how it got there in one line and the receipt one tap away. The search's
 * order is not the agent's recommendation, so the plate says which it is.
 */
export function LeadResult({ product, imageSrc, verdict, missionNote, searchNumber, onWhy }: {
  product: ProductSummary;
  imageSrc?: string;
  verdict: AgentVerdict;
  searchNumber: number;
  /** When a lab names its target: whether this is it. */
  missionNote?: { text: string; missing: boolean };
  onWhy: () => void;
}) {
  const signals = product.signals;
  const found = foundBySentence(product);
  const positions = [
    rank(signals?.pre_rerank_rank) ? `before reranking ${rank(signals?.pre_rerank_rank)}` : null,
    rank(signals?.final_rank) ? `final ${rank(signals?.final_rank)}` : null,
  ].filter(Boolean);
  const path = [found, ...positions].filter(Boolean).join(" · ");
  return (
    <section className="pg-lead" aria-label="First search result">
      <Link href={`/products/${product.product_id}`} className="pg-lead-photo" aria-label={`Open ${product.title}`}>
        <img src={imageSrc} alt="" decoding="async" />
      </Link>
      <div className="pg-lead-copy">
      <h2>{pickName(product)}</h2>
      <p className="pg-lead-position">Search {searchNumber}{rank(signals?.final_rank) ? ` · Result ${rank(signals?.final_rank)}` : " · First returned result"}</p>
      {path ? <p className="pg-lead-path">{path}</p> : null}
      {missionNote ? <p className="pg-lead-verdict" data-verdict={missionNote.missing ? "declined" : "picked"}>{missionNote.text}</p> : null}
      {verdict ? <p className="pg-lead-verdict" data-verdict={verdict}>{VERDICT[verdict]}</p> : null}
      <p className="pg-lead-links">
        <button type="button" onClick={onWhy}>Why this position</button>
        {product.listing_url ? (
          <a href={product.listing_url} target="_blank" rel="noreferrer">Original listing <ArrowUpRight size={14} aria-hidden="true" /></a>
        ) : (
          <Link href={`/products/${product.product_id}`}>Product details</Link>
        )}
      </p>
      </div>
    </section>
  );
}
