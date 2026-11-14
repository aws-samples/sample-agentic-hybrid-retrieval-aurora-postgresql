import { ArrowUpRight, Star } from "lucide-react";
import { useState } from "react";
import type { AgentCitation, ProductSummary } from "../../types";
import { sourceAnchor } from "./citations";
import { isReview, pickName } from "./comparison";
import { plural } from "./findings";
import { MarkedText } from "./MarkedText";
import { citedExcerpt, listFigures, recordText } from "./quoteLines";

/** The record in full, rendered only once opened, so a closed one adds nothing to the page. */
function WholeRecord({ quote, kind }: { quote: string; kind: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="ask-source-whole" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Read the whole {kind}</summary>
      {open ? <div>{recordText(quote).map((line, index) => <p key={index}>{line}</p>)}</div> : null}
    </details>
  );
}

/**
 * The answer's sources on hairlines, numbered as the prose and the picks cite
 * them. Each shows the line it was cited for, the cited figure marked, says which
 * of the claim's figures the record never states, and opens to the whole record.
 * Builder view adds each record's id, revision and type.
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
        {citations.map((citation) => {
          const excerpt = citedExcerpt(citation, answer);
          const kind = isReview(citation) ? "review" : "listing";
          return (
            <li key={citation.number} id={sourceAnchor(answerId, citation.number)} tabIndex={-1} value={citation.number}>
              <span className="ask-source-number">{citation.number}</span>
              <div>
                <p className="ask-source-head">
                  {nameFor(citation.product_id) ? <strong>{nameFor(citation.product_id)}</strong> : null}
                  <span className="ask-pill ask-pill-quiet">{isReview(citation) ? "Review" : "Listing"}</span>
                  {isReview(citation) && citation.rating != null ? (
                    <span className="ask-source-stars" aria-label={`Rated ${citation.rating.toFixed(1)} out of 5`}>
                      <Star size={12} fill="currentColor" aria-hidden="true" />{citation.rating.toFixed(1)}
                    </span>
                  ) : null}
                  {isReview(citation) && citation.title ? <span>{citation.title}</span> : null}
                </p>
                {excerpt.line ? (
                  <p className="ask-source-quote" data-figure={excerpt.marks.length ? "" : undefined}>
                    “<MarkedText text={excerpt.line} marks={excerpt.marks} />”
                  </p>
                ) : null}
                {excerpt.unstated.length ? (
                  <p className="ask-source-unstated">No line in this record states {listFigures(excerpt.unstated)}.</p>
                ) : null}
                <WholeRecord quote={citation.quote} kind={kind} />
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
          );
        })}
      </ol>
    </section>
  );
}
