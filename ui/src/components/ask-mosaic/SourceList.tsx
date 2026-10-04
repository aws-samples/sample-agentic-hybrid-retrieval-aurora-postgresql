import { ArrowUpRight } from "lucide-react";
import type { AgentCitation, ProductSummary } from "../../types";
import { sourceAnchor } from "./citations";
import { isReview, pickName } from "./comparison";
import { plural } from "./findings";
import { citedLine } from "./quoteLines";


/** What the sources leave open, stated rather than filled. */
export function StillUnknown({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <section className="ask-unknown" aria-label="Still unknown">
      <h4>Still unknown</h4>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

/**
 * The answer's sources on hairlines, numbered as the prose and the picks cite
 * them. Builder view adds each record's id, revision and type.
 */
export function SourceList({
  citations,
  products,
  answer,
  answerId,
  builder,
}: {
  citations: AgentCitation[];
  products: ProductSummary[];
  /** The answer's text, so each record shows the line it was cited for. */
  answer: string;
  answerId: string;
  builder: boolean;
}) {
  const reviews = citations.filter(isReview).length;
  const listings = citations.length - reviews;
  const nameFor = (productId: number) => {
    const product = products.find((item) => item.product_id === productId);
    return product ? pickName(product) : null;
  };
  return (
    <section className="ask-sources" aria-label="Sources">
      <h4>
        Sources
        <span>{plural(listings, "listing")} · {plural(reviews, "review")}</span>
      </h4>
      <ol>
        {citations.map((citation) => (
          <li key={citation.number} id={sourceAnchor(answerId, citation.number)} tabIndex={-1} value={citation.number}>
            <span className="ask-source-number">{citation.number}</span>
            <div>
              <p className="ask-source-head">
                {nameFor(citation.product_id) ? <strong>{nameFor(citation.product_id)}</strong> : null}
                <span className="ask-pill ask-pill-quiet">{isReview(citation) ? "Review" : "Listing"}</span>
                {isReview(citation) && citation.title ? <span>{citation.title}</span> : null}
              </p>
              {citedLine(citation, answer) ? <p className="ask-source-quote">“{citedLine(citation, answer)}”</p> : null}
              {builder ? (
                <p className="ask-mono ask-source-record">
                  <a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">
                    evidence {citation.evidence_id} <ArrowUpRight size={11} aria-hidden="true" />
                  </a>
                  {` · revision ${citation.revision} · ${citation.evidence_type}`}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
