import { Fragment } from "react";
import { armLabel, armPoolKey } from "../../retrievalLanguage";
import { toolName } from "../ask-mosaic/toolChips";
import type { SearchResponse, ToolTraceStep } from "../../types";
import type { PipelinePhase } from "../../usePipelineRun";

type ChipState = "running" | "done" | "failed" | "quiet" | "record";

interface Chip {
  key: string;
  label: string;
  value?: string;
  state: ChipState;
  /** Draw an arrow before this chip: the next stage of the pipeline. */
  then?: boolean;
  title?: string;
}

const duration = (value: number | null | undefined) =>
  value == null ? undefined : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;

/**
 * A search as the pipeline ran it: what each search put into the combined pool,
 * the pool Aurora combined, then reranking and what was shown. Counts and
 * timings are the search's own record; the three searches and the combination
 * run as one Aurora query, so only that query has a time.
 */
export function searchChips(response: SearchResponse): Chip[] {
  const diagnostics = response.diagnostics;
  const counts = diagnostics?.candidate_counts ?? {};
  const timings = diagnostics?.stage_timings_ms ?? {};
  const arms = (["fts", "trigram", "semantic"] as const).map((arm): Chip => {
    const count = counts[armPoolKey[arm]];
    return {
      key: arm,
      label: armLabel[arm],
      value: count == null ? undefined : String(count),
      state: count ? "done" : "quiet",
      title: count == null ? undefined : `${count} of this search’s matches are in the combined pool`,
    };
  });
  const reranked = diagnostics?.rerank_status === "applied";
  return [
    ...arms,
    {
      key: "combined",
      label: "Combined in Aurora",
      value: [counts.fused_pool == null ? null : String(counts.fused_pool), duration(timings.postgresql_retrieval)].filter(Boolean).join(" · ") || undefined,
      state: "done",
      then: true,
      title: "All three searches and reciprocal rank fusion ran in one Aurora PostgreSQL query",
    },
    { key: "rerank", label: reranked ? "Reranked" : "Not reranked", value: reranked ? duration(timings.rerank) : undefined, state: reranked ? "done" : "quiet", then: true },
    { key: "shown", label: "Shown", value: String(response.results.length), state: "done", then: true },
  ];
}

const RUNNING: Record<PipelinePhase, string> = { retrieve: "Searching", rank: "Comparing", reason: "Writing the answer" };

/** The Retrieval agent's tool calls as they finish, then the one still running. */
export function agentChips(trace: ToolTraceStep[], phase: PipelinePhase | null, running: boolean): Chip[] {
  const chips = trace.map((step): Chip => {
    const label = toolName(step);
    return {
      key: `step-${step.sequence}`,
      label,
      value: duration(step.latency_ms),
      state: step.outcome === "success" ? "done" : step.outcome === "error" ? "failed" : "quiet",
      title: step.detail,
    };
  });
  return running ? [...chips, { key: "running", label: RUNNING[phase ?? "retrieve"], state: "running" }] : chips;
}

/** One row of step chips, pg_sherlock style: a state dot, the step, its value. */
export function RunSteps({ chips, label }: { chips: Chip[]; label: string }) {
  if (!chips.length) return null;
  return <ol className="pg-chips" aria-label={label}>
    {chips.map((chip) => <Fragment key={chip.key}>
      {chip.then ? <li className="pg-chip-then" aria-hidden="true">→</li> : null}
      <li className="pg-chip" data-state={chip.state} title={chip.title}>
        {chip.label}{chip.value ? <span>{chip.value}</span> : null}
      </li>
    </Fragment>)}
  </ol>;
}

/** The one chip a search shows before its record arrives. */
export function searchingChips(): Chip[] {
  return [{ key: "running", label: "Searching Aurora", state: "running" }];
}

/** The saved search's record ID, short on the chip and whole on hover. */
export function recordChip(searchEventId: string): Chip {
  return { key: "record", label: "Record", value: searchEventId.slice(0, 8), state: "record", title: `Search record ${searchEventId}` };
}
