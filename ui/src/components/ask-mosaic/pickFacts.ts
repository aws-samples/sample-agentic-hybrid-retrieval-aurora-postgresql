import { specFacts } from "../../format";
import type { AgentCitation, ProductSummary } from "../../types";
import { isReview, type ComparisonRow } from "./comparison";

/** A fact about a pick, with the citation that backs it when there is one. */
export interface PickFact {
  text: string;
  /** The citation number whose record contains the words, or null for a listing spec. */
  number: number | null;
}

/** A stated requirement judged against the listing's own typed value. */
export interface PickRequirement {
  label: string;
  status: "met" | "not_met";
  value: string;
  citations: number[];
}

const FACT_LENGTH = 110;

/** The first sentence-sized stretch of a record's words, cut at a word. */
export function excerpt(text: string, length = FACT_LENGTH): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > length ? `${flat.slice(0, length).replace(/\s\S*$/, "")}…` : flat;
}

/**
 * Up to two facts for a pick, each quoted from a record the answer cited: one
 * the listing states and one a reviewer wrote. A pick the answer cites nothing
 * for falls back to what its listing states, without a citation.
 */
export function pickFacts(product: ProductSummary, citations: AgentCitation[]): PickFact[] {
  const own = citations.filter((citation) => citation.product_id === product.product_id);
  // A listing's title record only repeats the product's name; a fact needs more.
  const listing = own.find((citation) => (
    !isReview(citation) && citation.quote && !/^title:/i.test(citation.quote.trim())
  ));
  const review = own.find((citation) => isReview(citation) && citation.quote);
  const cited: PickFact[] = [
    ...(listing ? [{ text: excerpt(listing.quote), number: listing.number }] : []),
    ...(review ? [{ text: `“${excerpt(review.quote)}”`, number: review.number }] : []),
  ];
  if (cited.length === 2) return cited;
  const stated = specFacts(product.specs, 2).map((fact) => ({ text: `${fact.label}: ${fact.value}`, number: null }));
  return [...cited, ...stated].slice(0, 2);
}

/** The requirements the shopper stated, as this pick's cell in each row decided them. */
export function pickRequirements(rows: ComparisonRow[], index: number): PickRequirement[] {
  return rows.flatMap((row) => {
    const cell = row.cells[index];
    return cell?.status ? [{ label: row.label, status: cell.status, value: cell.text, citations: cell.citations }] : [];
  });
}
