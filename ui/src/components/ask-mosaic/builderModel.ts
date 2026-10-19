import { formatCategoryKey } from "../../format";
import type { AgentPlanStep, AgentResponse, ToolTraceStep } from "../../types";
import { formatDuration } from "./findings";
import type { AssistStage } from "./types";

/** A stage colour for a tag's dot, or null for a neutral one. */
export type TagStage = "retrieve" | "rank" | "reason" | "problem" | null;

export interface StepTag {
  label: string;
  stage: TagStage;
}

export interface BuilderStep {
  key: string;
  tool: string;
  tags: StepTag[];
  /** Result count, latency and run id, in the order the trace records them. */
  meta: string;
  args: string;
  detail: string;
}

/**
 * The phase each registered tool belongs to. A tool this table does not know is
 * filed under the last phase rather than dropped, so the timeline never hides a
 * recorded step.
 */
const TOOL_PHASE: Record<string, AssistStage> = {
  search_products: "retrieve",
  compare_products: "rank",
  explain_retrieval: "rank",
  get_product_evidence: "rank",
  synthesize_cited_answer: "answer",
};

const TOOL_TAGS: Record<string, StepTag[]> = {
  search_products: [
    { label: "Aurora search", stage: "retrieve" },
    { label: "Combine and rerank", stage: "rank" },
  ],
  compare_products: [{ label: "Aurora", stage: "retrieve" }],
  explain_retrieval: [{ label: "Saved receipts", stage: null }],
  get_product_evidence: [{ label: "Aurora evidence", stage: "retrieve" }],
  synthesize_cited_answer: [
    { label: "Retrieval agent", stage: "reason" },
    { label: "Citation checks", stage: "reason" },
  ],
};

const ORIGIN_LABEL: Record<NonNullable<ToolTraceStep["origin"]>, string> = {
  model: "Requested by the model",
  controller_fallback: "Started by the application",
};

const ROUTE_LABEL: Record<NonNullable<ToolTraceStep["route"]>, string> = {
  gateway: "Through AgentCore Gateway",
  in_process: "Without Gateway",
};

const OUTCOME_LABEL: Record<ToolTraceStep["outcome"], string> = {
  success: "Step completed",
  error: "Step failed",
  denied: "Step declined",
};

/** Arguments as `key=value` pairs, in the mono type ids and queries use. */
export function formatArguments(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(" ");
}

function traceStep(step: ToolTraceStep): BuilderStep {
  const meta = [
    step.result_count != null ? `${step.result_count} results` : null,
    step.latency_ms != null ? formatDuration(step.latency_ms) : null,
    step.retrieval_run_id ? step.retrieval_run_id.slice(0, 8) : null,
    step.search_sql_sha256 ? `SQL ${step.search_sql_sha256.slice(0, 12)}` : null,
  ].filter(Boolean).join(" · ");
  return {
    key: `trace-${step.sequence}`,
    tool: step.tool,
    tags: [
      ...(TOOL_TAGS[step.tool] ?? []),
      ...(step.route ? [{ label: ROUTE_LABEL[step.route], stage: null }] : []),
      ...(step.origin ? [{ label: ORIGIN_LABEL[step.origin], stage: null }] : []),
      { label: OUTCOME_LABEL[step.outcome] ?? step.outcome, stage: step.outcome === "error" ? "problem" : null },
    ],
    meta,
    args: formatArguments(step.arguments ?? {}),
    detail: step.detail,
  };
}

function planStep(plan: AgentPlanStep[]): BuilderStep {
  return {
    key: "plan",
    tool: "plan",
    tags: [{ label: "Retrieval agent", stage: "reason" }],
    meta: `${plan.length} ${plan.length === 1 ? "search" : "searches"}`,
    args: plan
      .map((step) => (
        step.filters.category_key
          ? `"${step.query}" ${formatCategoryKey(step.filters.category_key)}`
          : `"${step.query}"`
      ))
      .join(" · "),
    detail: "",
  };
}

/** The recorded steps of one phase, built from the plan and the trace and nothing else. */
export function stepsFor(stage: AssistStage, plan: AgentPlanStep[], trace: ToolTraceStep[]): BuilderStep[] {
  if (stage === "understand") return plan.length ? [planStep(plan)] : [];
  return trace.filter((step) => (TOOL_PHASE[step.tool] ?? "answer") === stage).map(traceStep);
}

/**
 * Facts about the run itself. `AgentResponse` and `ToolTraceStep` carry no
 * model id, token counts, Gateway target or per-claim verdicts, so none is
 * printed: a value that was not recorded is left out, never guessed.
 */
export function runFacts(response: AgentResponse, durationMs?: number): string[] {
  return [
    ...(response.session_id ? [`session ${response.session_id.slice(0, 8)}`] : []),
    response.outcome ?? "grounded",
    ...(durationMs != null ? [formatDuration(durationMs)] : []),
    response.memory?.enabled ? "memory on" : "memory off",
  ];
}
