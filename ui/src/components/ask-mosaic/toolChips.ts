import { formatCategoryKey } from "../../format";
import type { ToolTraceStep } from "../../types";

/** How a chip reads: done is green, failed is red, denied stays grey. */
export type ChipState = "done" | "failed" | "denied";

export interface ToolChip {
  key: string;
  label: string;
  /** The tool's own name, as the terminal's TOOL TRACE and the builder view print it. */
  tool: string;
  state: ChipState;
  /** Measured tool time, shown only once the tool is done. */
  latencyMs: number | null;
}

/** The longest query a Search chip carries before it falls back to the category. */
const QUERY_FITS = 24;

const TOOL_NAME: Record<string, string> = {
  search_products: "Search",
  get_product_evidence: "Read sources",
  compare_products: "Compare",
  explain_retrieval: "Explain ranking",
  synthesize_cited_answer: "Write cited answer",
};

/** "Search", plus the search's own short query or its category when that fits. */
export function toolName(step: Pick<ToolTraceStep, "tool" | "arguments">): string {
  const name = TOOL_NAME[step.tool] ?? step.tool.replace(/_/g, " ");
  if (step.tool !== "search_products") return name;
  const { query, category_key: category } = step.arguments ?? {};
  if (typeof query === "string" && query.trim() && query.trim().length <= QUERY_FITS) return `${name} ${query.trim()}`;
  return typeof category === "string" && category ? `${name} ${formatCategoryKey(category)}` : name;
}

const STATE_FOR_OUTCOME: Record<ToolTraceStep["outcome"], ChipState> = {
  success: "done",
  error: "failed",
  denied: "denied",
};

/**
 * One chip per recorded tool call, in the order the trace recorded them. The
 * trace is the only source; nothing is listed before it was recorded. The phase
 * in progress is the status line's spinner, not a chip.
 */
export function toolChips(trace: ToolTraceStep[]): ToolChip[] {
  return trace.map((step): ToolChip => ({
    key: `trace-${step.sequence}`,
    label: toolName(step),
    tool: step.tool,
    state: STATE_FOR_OUTCOME[step.outcome] ?? "failed",
    latencyMs: step.latency_ms ?? null,
  }));
}

export const formatMilliseconds = (milliseconds: number): string => (
  `${Math.round(milliseconds).toLocaleString("en-US")} ms`
);
