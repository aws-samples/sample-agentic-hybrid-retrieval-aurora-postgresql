import { specFacts } from "../../format";
import type { AgentCitation, ProductSummary } from "../../types";
import { isReview, type ComparisonRow } from "./comparison";
import { quotedLine } from "./quoteLines";

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

/**
 * Up to two facts for a pick, each a whole line from a record the answer cited:
 * the listing line and the review sentence that best support what the answer
 * said. A pick the answer cites nothing usable for falls back to what its
 * listing states, without a citation.
 */
export function pickFacts(product: ProductSummary, citations: AgentCitation[], answer = ""): PickFact[] {
  const own = citations.filter((citation) => citation.product_id === product.product_id);
  const first = (review: boolean): PickFact[] => {
    for (const citation of own.filter((item) => isReview(item) === review)) {
      const text = quotedLine(citation, answer);
      if (text) return [{ text, number: citation.number }];
    }
    return [];
  };
  const cited = [...first(false), ...first(true)];
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
