import { formatCategoryKey } from "../../format";
import type { AgentCitation, AgentPlanStep, ToolTraceStep } from "../../types";
import { isReview } from "./comparison";
import { stagesFor, type AssistExecutionPath, type AssistStage } from "./types";

/**
 * One-line findings for each phase of a run, counted from the response or the
 * partial the stream has delivered. Nothing here is written in advance: a phase
 * that did nothing says so, and a count is a count of recorded rows.
 */
export interface RunData {
  path: AssistExecutionPath;
  plan: AgentPlanStep[];
  trace: ToolTraceStep[];
  citations: AgentCitation[];
}

export const plural = (count: number, one: string, many = `${one}s`) => (
  `${count} ${count === 1 ? one : many}`
);

const steps = (trace: ToolTraceStep[], tool: string) => (
  trace.filter((step) => step.tool === tool)
);

function comparedProducts(step: ToolTraceStep): number | null {
  const ids = step.arguments?.product_ids;
  if (Array.isArray(ids)) return ids.length;
  return step.result_count;
}

function understood(run: RunData): string | null {
  if (!run.plan.length) {
    return run.path === "focused_follow_up" ? "Reused the earlier shortlist." : null;
  }
  const categories = [...new Set(
    run.plan.flatMap((step) => (step.filters.category_key ? [formatCategoryKey(step.filters.category_key)] : [])),
  )];
  const searches = plural(run.plan.length, "search", "searches");
  return categories.length ? `Planned ${searches}: ${categories.join(", ")}.` : `Planned ${searches}.`;
}

function searched(run: RunData): string | null {
  const searches = steps(run.trace, "search_products");
  if (!searches.length) return null;
  const counted = searches.every((step) => step.result_count != null);
  const kept = searches.reduce((total, step) => total + (step.result_count ?? 0), 0);
  const ran = `Ran ${plural(searches.length, "search", "searches")} in Aurora`;
  return counted ? `${ran} and kept ${plural(kept, "product")}.` : `${ran}.`;
}

function compared(run: RunData): string {
  const comparisons = steps(run.trace, "compare_products").filter((step) => step.outcome === "success");
  const replays = steps(run.trace, "explain_retrieval").length;
  if (!comparisons.length && !replays) return "No comparison step was recorded.";
  const products = Math.max(0, ...comparisons.map((step) => comparedProducts(step) ?? 0));
  const parts = [
    ...(comparisons.length ? [`Compared ${products ? plural(products, "product") : "the picks"}`] : []),
    ...(replays ? [`replayed the ranking of ${plural(replays, "search", "searches")}`] : []),
  ];
  const sentence = parts.join(" and ");
  return `${sentence}.`;
}

function checked(run: RunData): string {
  if (!run.citations.length) return "No sources were cited.";
  const reviews = run.citations.filter(isReview).length;
  const listings = run.citations.length - reviews;
  const reads = steps(run.trace, "get_product_evidence").length;
  const after = reads ? `, after ${plural(reads, "evidence read")}` : "";
  return `${plural(run.citations.length, "citation")}: ${listings} from listings and ${reviews} from reviews${after}.`;
}

/** The finding for a phase that has finished, or null while there is nothing to count yet. */
export function phaseFinding(stage: AssistStage, run: RunData): string | null {
  if (stage === "understand") return understood(run);
  if (stage === "retrieve") return searched(run);
  if (stage === "rank") return compared(run);
  return checked(run);
}

const seconds = (milliseconds: number) => `${(milliseconds / 1000).toFixed(1)} s`;

export const formatDuration = seconds;

/** "4 steps · 3 searches · 6 sources · 43.5 s", from the same recorded rows. */
export function runSummary(run: RunData, durationMs?: number): string {
  const searches = steps(run.trace, "search_products").length;
  return [
    plural(stagesFor(run.path).length, "step"),
    plural(searches, "search", "searches"),
    plural(run.citations.length, "source"),
    ...(durationMs != null ? [seconds(durationMs)] : []),
  ].join(" · ");
}
