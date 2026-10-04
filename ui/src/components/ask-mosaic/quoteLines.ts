import type { AgentCitation } from "../../types";
import { isReview } from "./comparison";

/**
 * Whole lines from an evidence record, and the one that supports a claim.
 *
 * A record is stored as it was ingested: a listing starts with `Title:` and
 * `Categories:` headers and a `Description:` label, and a review can carry
 * `<br />` breaks. Neither is something to quote at a shopper. Every line
 * returned here is an exact piece of the record's own words, cut at sentence
 * ends, so a fragment never stands in for a sentence.
 */

const HEADER = /^(title|categories)\s*:/i;
const DESCRIPTION_LABEL = /^description\s*:\s*/i;
// A sentence end, then a capital or digit; sellers also run sentences together ("more.A new").
const SENTENCE_END = /(?<=[a-z0-9”")][.!?])(?:\s+|(?=[A-Z]))(?=[A-Z0-9“"(])/;
const MIN_LINE = 12;

/** Sentences and spec lines of a record, boilerplate and markup removed. */
export function recordSentences(quote: string): string[] {
  return quote
    .split(/<br\s*\/?>|\n/i)
    .map((line) => line.trim().replace(DESCRIPTION_LABEL, ""))
    .filter((line) => line && !HEADER.test(line))
    .flatMap((line) => line.split(SENTENCE_END))
    .map((line) => line.trim())
    .filter((line) => line.length >= MIN_LINE);
}

const BOUNDARY = /(?<=[.!?])\s+(?=[A-Z#])|[;\n]/;

/** The clause of the answer that carries citation `number`, without other citation marks. */
export function citedClaim(answer: string, number: number): string {
  const at = answer.indexOf(`[${number}]`);
  if (at < 0) return "";
  const before = answer.slice(0, at);
  const clause = before.split(BOUNDARY).at(-1) ?? "";
  return clause.replace(/\[\d+\]/g, "").trim();
}

const STOPWORDS = new Set([
  "this", "that", "with", "from", "have", "has", "their", "your", "they", "them", "than", "then",
  "though", "which", "while", "over", "into", "also", "such", "does", "doesn", "about", "here",
  "there", "when", "what", "were", "been", "being", "will", "would", "could", "should", "very",
  "reviewer", "reviewers", "reports", "describes", "says", "lists", "listing", "specifies",
]);

const terms = (text: string) => new Set(
  (text.toLowerCase().match(/[a-z0-9]{4,}/g) ?? []).filter((word) => !STOPWORDS.has(word)),
);

/**
 * The line of the record that best supports what the answer cited it for.
 *
 * Lines are scored by how many of the claim's terms they share; a tie, or no
 * overlap at all, keeps the earliest line, which is the first feature or the
 * review's opening sentence. Empty when the record is only boilerplate.
 */
export function citedLine(citation: AgentCitation, answer: string): string {
  const lines = recordSentences(citation.quote);
  if (!lines.length) return "";
  // The product's own name appears in every line of the claim and says nothing about support.
  const name = terms(/^title\s*:(.*)$/im.exec(citation.quote)?.[1] ?? "");
  const claim = terms(citedClaim(answer, citation.number));
  let best = lines[0];
  let bestScore = 0;
  for (const line of lines) {
    const score = [...terms(line)].filter((word) => claim.has(word) && !name.has(word)).length;
    if (score > bestScore) {
      best = line;
      bestScore = score;
    }
  }
  return best;
}

/** A citation's line, quoted when a reviewer wrote it. */
export function quotedLine(citation: AgentCitation, answer: string): string {
  const line = citedLine(citation, answer);
  return line && isReview(citation) ? `“${line}”` : line;
}
