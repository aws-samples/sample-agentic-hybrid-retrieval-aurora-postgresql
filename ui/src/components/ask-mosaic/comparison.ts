import { formatAttributeLabel, specFacts } from "../../format";
import { armLabel } from "../../retrievalLanguage";
import type { AgentCitation, ProductSpec, ProductSummary, ToolTraceStep } from "../../types";

/**
 * The answer's comparison, derived only from what the response carries.
 *
 * Every cell says where its fact came from: a spec field the listing states, a
 * figure found only in the title, a review, or nothing at all. A requirement is
 * read from the shopper's own words and decided against the stated value, never
 * against prose, so "Not met" means the listing states less than was asked. A
 * cell cites a record only when that record's text contains the quoted figure.
 */

export type CellSource = "listing" | "title" | "review" | "not_stated";
export type RequirementStatus = "met" | "not_met" | null;

export interface ComparisonCell {
  text: string;
  source: CellSource;
  citations: number[];
  status: RequirementStatus;
}

export interface ComparisonRow {
  key: string;
  label: string;
  cells: ComparisonCell[];
  /** A requirement from the latest question, drawn as the change it is. */
  changed: boolean;
}

interface Requirement {
  key: "usb_c_power_w" | "size_in" | "refresh_hz" | "resolution";
  label: string;
  meets: (value: unknown) => boolean;
}

const LISTING_TITLE_BREAK = / \(| - | \| |, /;

/**
 * A listing's own words, short enough for a table header. A bare number right
 * after the same figure in inches is dropped: sellers write `27" 27 4K`.
 */
export function pickName(product: ProductSummary): string {
  if (!product.source_dataset) return `${product.brand} ${product.model}`.trim();
  const words = product.title.split(LISTING_TITLE_BREAK)[0].replace(/"/g, "″").split(/\s+/);
  const kept = words.filter((word, index) => !(index && words[index - 1] === `${word}″`));
  return kept.slice(0, 5).join(" ");
}

/** The measurable requirements a question states, in the spec fields that decide them. */
export function requirementsFrom(question: string): Requirement[] {
  const found: Requirement[] = [];
  const watts = /(?<![\d.])(\d{2,3})\s?(?:w|watts?)\b/i.exec(question);
  if (watts) {
    const bound = Number(watts[1]);
    found.push({ key: "usb_c_power_w", label: `${bound}W charging`, meets: (value) => Number(value) >= bound });
  }
  const inches = /(?<![\d.])(\d{2}(?:\.\d)?)\s?(?:"|”|″|-?\s?inch(?:es)?\b)/i.exec(question);
  if (inches) {
    const size = Number(inches[1]);
    found.push({ key: "size_in", label: `${inches[1]}-inch screen`, meets: (value) => Math.abs(Number(value) - size) <= 1 });
  }
  if (/\b4k\b|3840\s?[x×]\s?2160/i.test(question)) {
    found.push({ key: "resolution", label: "4K, 3840 × 2160", meets: (value) => value === "3840x2160" });
  }
  const hertz = /(?<![\d.])(\d{2,3})\s?hz\b/i.exec(question);
  if (hertz) {
    const bound = Number(hertz[1]);
    found.push({ key: "refresh_hz", label: `${bound} Hz or faster`, meets: (value) => Number(value) >= bound });
  }
  return found;
}

export const isReview = (citation: AgentCitation) => /review/i.test(citation.evidence_type);

const comparable = (text: string) => text.replace(/\s+/g, " ").trim().toLowerCase();

/** The pick's cited listing records whose text states this figure verbatim. */
function specCitations(product: ProductSummary, spec: ProductSpec, citations: AgentCitation[]): number[] {
  const figure = comparable(spec.quote);
  return citations
    .filter((citation) => (
      citation.product_id === product.product_id
      && !isReview(citation)
      && Boolean(figure)
      && comparable(citation.quote).includes(figure)
    ))
    .map((citation) => citation.number);
}

/**
 * One row per typed spec any pick states, plus every requirement the shopper
 * named, then the reviewers. `questions` runs oldest first; requirements from
 * the last one are marked as changed.
 */
export function comparisonRows(
  picks: ProductSummary[],
  citations: AgentCitation[],
  questions: string[],
): ComparisonRow[] {
  const latest = new Set<string>(requirementsFrom(questions.at(-1) ?? "").map((item) => item.key));
  const requirements = new Map<string, Requirement>();
  for (const question of questions) {
    for (const requirement of requirementsFrom(question)) requirements.set(requirement.key, requirement);
  }
  const keys = [
    ...new Set([
      ...picks.flatMap((pick) => specFacts(pick.specs).map((fact) => fact.key)),
      ...requirements.keys(),
    ]),
  ];
  const rows: ComparisonRow[] = keys.map((key) => {
    const requirement = requirements.get(key);
    return {
      key,
      label: requirement?.label ?? formatAttributeLabel(key),
      changed: latest.has(key) && questions.length > 1,
      cells: picks.map((pick) => {
        const fact = specFacts(pick.specs).find((item) => item.key === key);
        const spec = pick.specs?.[key];
        if (!fact || !spec) {
          return { text: "Not stated", source: "not_stated", citations: [], status: null };
        }
        return {
          text: fact.value,
          source: spec.source === "title" ? "title" : "listing",
          citations: specCitations(pick, spec, citations),
          status: requirement ? (requirement.meets(spec.value) ? "met" : "not_met") : null,
        };
      }),
    };
  });
  rows.push({
    key: "reviews",
    label: "Reviewers",
    changed: false,
    cells: picks.map((pick) => {
      const reviews = citations.filter((citation) => citation.product_id === pick.product_id && isReview(citation));
      return reviews.length
        ? { text: reviews.length === 1 ? "1 review cited" : `${reviews.length} reviews cited`, source: "review", citations: reviews.map((c) => c.number), status: null }
        : { text: "None cited", source: "not_stated", citations: [], status: null };
    }),
  });
  return rows;
}

/** "Meaning #7 → Combined #10 → Reranked to #1", from the pick's own signals. */
export function retrievalPath(product: ProductSummary): string[] {
  const signals = product.signals;
  if (!signals) return [];
  const found = (["fts", "trigram", "semantic"] as const)
    .filter((arm) => signals[arm]?.rank != null)
    .map((arm) => `${armLabel[arm]} #${signals[arm].rank}`);
  return [
    ...found,
    ...(signals.pre_rerank_rank != null ? [`Combined #${signals.pre_rerank_rank}`] : []),
    ...(signals.final_rank != null ? [`Reranked to #${signals.final_rank}`] : []),
  ];
}

/** What the sources leave open, stated rather than filled. */
export function unknowns(picks: ProductSummary[], rows: ComparisonRow[]): string[] {
  const missing = rows
    .filter((row) => row.key !== "reviews")
    .flatMap((row) => row.cells.flatMap((cell, index) => (
      cell.source === "not_stated" ? [`${row.label}: not stated for ${pickName(picks[index])}`] : []
    )));
  return [...missing, "Current price and stock"];
}

/**
 * The live line's resolved text: what the run did, in one line.
 * "Searched monitors, kept 2 · read evidence for 2 · 22 s".
 */
export function activitySummary(trace: ToolTraceStep[]): string {
  const searches = trace.filter((step) => step.tool === "search_products");
  const reads = trace.filter((step) => step.tool === "get_product_evidence").length;
  const rewrites = trace.filter(
    (step) => step.tool === "synthesize_cited_answer" && step.outcome === "error",
  ).length;
  const seconds = trace.reduce((total, step) => total + (step.latency_ms ?? 0), 0) / 1000;
  const parts: string[] = [];
  if (searches.length) {
    const category = searches[0].arguments?.category_key;
    const noun = typeof category === "string"
      ? (category.endsWith("s") ? category : `${category}s`).replace(/_/g, " ")
      : "the catalog";
    const kept = searches.at(-1)?.result_count;
    parts.push(`Searched ${noun}${searches.length > 1 ? ` ${searches.length} times` : ""}${kept != null ? `, kept ${kept}` : ""}`);
  } else if (trace.some((step) => step.tool === "compare_products")) {
    parts.push("Compared your picks");
  }
  if (reads) parts.push(`read evidence for ${reads}`);
  if (rewrites) parts.push(`rewrote the answer ${rewrites}×`);
  if (seconds >= 1) parts.push(`${Math.round(seconds)} s`);
  return parts.join(" · ");
}
