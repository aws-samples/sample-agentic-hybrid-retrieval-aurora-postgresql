import { AlertTriangle, Check, LoaderCircle, Minus } from "lucide-react";
import { useEffect, useState } from "react";
import type { AgentStreamEvent } from "../api";

export type AgentPhase = Extract<AgentStreamEvent, { type: "stage" }>;

const phaseLabels: Record<AgentPhase["id"], string> = {
  understand: "Interpreting the request",
  retrieve: "Retrieving products and evidence",
  rank: "Comparing product records",
  answer: "Preparing the cited answer",
};

export function ReasonRunStatus({
  phase, loading, startedAt, finishedAt, error, declined, runId,
  searchCount, productCount, toolCount,
}: {
  phase: AgentPhase | null;
  loading: boolean;
  startedAt: number;
  finishedAt: number | null;
  error: string;
  declined: boolean;
  runId?: string;
  searchCount: number;
  productCount: number;
  toolCount: number;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!loading) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [loading, startedAt]);

  const elapsed = Math.max(0, Math.floor(((finishedAt ?? now) - startedAt) / 1000));
  const title = error ? "Run interrupted"
    : loading ? phase ? phaseLabels[phase.id] : "Starting the agent"
      : declined ? "Request declined" : "Answer recorded";
  const detail = error ? phase
    ? `Last reported stage: ${phaseLabels[phase.id]}. Inspect the available records below.`
    : "The run did not complete. Inspect the recorded activity below."
    : loading ? phase?.detail ?? "Waiting for the first progress update from the service."
      : declined ? "The agent completed without a matching recommendation."
        : "The answer and its run receipt are ready to inspect.";

  return (
    <header className="labs-reason-run-status" data-state={error ? "error" : loading ? "running" : "settled"}>
      <div className="labs-reason-run-heading">
        {error ? <AlertTriangle size={20} aria-hidden="true" />
          : loading ? <LoaderCircle size={20} className="spin" aria-hidden="true" />
            : declined ? <Minus size={20} aria-hidden="true" />
              : <Check size={20} aria-hidden="true" />}
        <div role="status" aria-live="polite" aria-atomic="true">
          <h3>{title}</h3>
          <p>{detail}</p>
        </div>
        <span className="labs-reason-elapsed" aria-label={`${elapsed} seconds elapsed`}>
          {elapsed}s <small>elapsed</small>
        </span>
      </div>
      <div className="labs-reason-run-meta">
        <dl aria-label="Agent run figures">
          <div><dt>Searches</dt><dd>{searchCount}</dd></div>
          <div><dt>Products in view</dt><dd>{productCount}</dd></div>
          <div><dt>Tool calls</dt><dd>{toolCount}</dd></div>
        </dl>
        {runId ? <span>Run <code>{runId.slice(0, 8)}</code></span> : null}
      </div>
    </header>
  );
}
