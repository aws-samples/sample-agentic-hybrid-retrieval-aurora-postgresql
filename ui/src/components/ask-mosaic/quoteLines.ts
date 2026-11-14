import type { AgentCitation } from "../../types";
import { isReview } from "./comparison";
import unitAliases from "./unitAliases.json";

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

/** A measurement the claim states: its digits and the unit family they are counted in. */
interface Figure {
  /** The claim's own wording, such as `100W`. */
  text: string;
  value: string;
  family: string;
}

const UNIT_FAMILY = new Map<string, string>(Object.entries(unitAliases));
const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// The answer check's own token: letters, digits, letters. Letters first make it a model
// ID (VG2756), and a bare number (Zone 900) is not a measurement.
const TOKEN = /(?<![A-Za-z0-9])[A-Za-z]*\d[\d,]*(?:\.\d+)?[A-Za-z]*/g;
const RESOLUTION = /(?<![A-Za-z0-9])(\d+)\s*[x×]\s*(\d+)(?![A-Za-z0-9])/gi;

/**
 * Each figure-and-unit the text states, as `synthesis._measurable_claims` reads one:
 * 90W, 90 W and 90 watts are one figure, and a resolution keeps both dimensions.
 */
function figures(text: string): Figure[] {
  const found: Figure[] = [];
  const taken: Array<[number, number]> = [];
  for (const match of text.matchAll(RESOLUTION)) {
    found.push({ text: match[0], value: `${match[1]}x${match[2]}`, family: "resolution" });
    taken.push([match.index, match.index + match[0].length]);
  }
  for (const match of text.matchAll(TOKEN)) {
    if (taken.some(([start, end]) => match.index >= start && match.index < end)) continue;
    const token = match[0].replace(/,/g, "");
    if (/^[A-Za-z]+\d/.test(token)) continue;
    const attached = /[A-Za-z]+$/.exec(token)?.[0];
    const following = /^[\s-]+([A-Za-z]+)/.exec(text.slice(match.index + match[0].length));
    const unit = attached ?? following?.[1];
    const family = unit ? UNIT_FAMILY.get(unit.toLowerCase()) : undefined;
    if (!family) continue;
    const value = /\d+(?:\.\d+)?/.exec(token)?.[0] ?? token;
    const end = match.index + match[0].length + (attached ? 0 : following?.[0].length ?? 0);
    found.push({ text: text.slice(match.index, end), value, family });
  }
  return found.filter((figure, index) => found.findIndex(
    (other) => other.value === figure.value && other.family === figure.family,
  ) === index);
}

/** Where `line` states `figure` in the same unit family, as [start, end] offsets. */
function statedAt(line: string, figure: Figure): [number, number] | null {
  const pattern = figure.family === "resolution"
    ? `${figure.value.replace("x", "\\s*[x×]\\s*")}`
    : `${escaped(figure.value)}[\\s-]*(?:${[...UNIT_FAMILY.keys()]
      .filter((alias) => UNIT_FAMILY.get(alias) === figure.family)
      .sort((a, b) => b.length - a.length)
      .map(escaped)
      .join("|")})`;
  const match = new RegExp(`(?<![A-Za-z0-9.,])${pattern}(?![A-Za-z0-9])`, "i").exec(line);
  return match ? [match.index, match.index + match[0].length] : null;
}

/** The line a citation was cited for, and what in it carries the claim's figures. */
export interface CitedExcerpt {
  /** A whole line of the record, in the record's own words. */
  line: string;
  /** Offsets in `line` of each figure the claim states, in the record's wording. */
  marks: Array<[number, number]>;
  /** Figures the claim states that the record states nowhere, in the claim's wording. */
  unstated: string[];
}

/**
 * The line of the record that best supports what the answer cited it for.
 *
 * A line that states the claim's figure in the same unit wins: “90W charging over one
 * cable” supports a 90W claim, and a USB hub sentence that shares more of its words does
 * not. Otherwise lines are scored by how many of the claim's terms they share; a tie, or
 * no overlap at all, keeps the earliest line, which is the first feature or the review's
 * opening sentence. The line is empty when the record is only boilerplate.
 * `scripts/cited_lines.py` gives the terminal the same line; `data/cited_line_cases.json`
 * holds both to it.
 */
export function citedExcerpt(citation: AgentCitation, answer: string): CitedExcerpt {
  const claimText = citedClaim(answer, citation.number);
  const wanted = figures(claimText);
  const unstated = wanted.filter((figure) => !statedAt(citation.quote, figure)).map((figure) => figure.text);
  const lines = recordSentences(citation.quote);
  if (!lines.length) return { line: "", marks: [], unstated };
  // The product's own name appears in every line of the claim and says nothing about support.
  const name = terms(/^title\s*:(.*)$/im.exec(citation.quote)?.[1] ?? "");
  const claim = terms(claimText);
  let best = { line: lines[0], marks: [] as Array<[number, number]>, score: 0 };
  for (const line of lines) {
    const at = wanted.flatMap((figure) => {
      const span = statedAt(line, figure);
      return span ? [span] : [];
    });
    const score = [...terms(line)].filter((word) => claim.has(word) && !name.has(word)).length;
    if (at.length > best.marks.length || (at.length === best.marks.length && score > best.score)) {
      best = { line, marks: at.sort((a, b) => a[0] - b[0]), score };
    }
  }
  return { line: best.line, marks: best.marks, unstated };
}

/**
 * Every line of a record, for “Read the whole listing”: the title as the product's name,
 * then the description and features in full. Only the ingest labels, the category path
 * and `<br />` breaks are left out.
 */
export function recordText(quote: string): string[] {
  return quote
    .split(/<br\s*\/?>|\n/i)
    .map((line) => line.trim().replace(/^(?:title|description)\s*:\s*/i, ""))
    .filter((line) => line && !/^categories\s*:/i.test(line));
}

/** Figures for a sentence: “100W”, “90W or 100W”, “5 hours, 90W or 100W”. */
export function listFigures(figures: string[]): string {
  return figures.length < 2 ? figures.join("") : `${figures.slice(0, -1).join(", ")} or ${figures.at(-1)}`;
}

/** The line a citation was cited for, as `citedExcerpt` chooses it. */
export function citedLine(citation: AgentCitation, answer: string): string {
  return citedExcerpt(citation, answer).line;
}

/** A citation's line with its marked figures, quoted when a reviewer wrote it. */
export function quotedExcerpt(citation: AgentCitation, answer: string): CitedExcerpt {
  const excerpt = citedExcerpt(citation, answer);
  if (!excerpt.line || !isReview(citation)) return excerpt;
  const marks = excerpt.marks.map(([start, end]): [number, number] => [start + 1, end + 1]);
  return { ...excerpt, line: `“${excerpt.line}”`, marks };
}

/** A citation's line, quoted when a reviewer wrote it. */
export function quotedLine(citation: AgentCitation, answer: string): string {
  return quotedExcerpt(citation, answer).line;
}
