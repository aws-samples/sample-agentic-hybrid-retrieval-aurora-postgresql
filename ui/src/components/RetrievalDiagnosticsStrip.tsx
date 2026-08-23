import { armLanguage, armPoolKey } from "../retrievalLanguage";
import type { RetrievalDiagnostics, SearchResponse } from "../types";

/**
 * The measured band for one retrieval run.
 *
 * Every figure here is read off the response the service just returned. There
 * is no placeholder state and no derived estimate: the strip only renders once
 * a query has actually run, so a participant reading a number can go find the
 * row it came from.
 *
 * The bars used to be labelled "Full-text / pg_trgm / Vector" — a third naming of
 * the three arms, half customer word and half feature name. They carry the shared
 * label now; the mechanism beside it lives in the channel list one panel up, where
 * there is room for it without squeezing the bar into three wrapped lines.
 */

const armLabels = armLanguage.map((arm) => ({
  key: armPoolKey[arm.key],
  label: arm.label,
}));

const timingLabels: Array<{ key: string; label: string }> = [
  { key: "embedding", label: "Embed" },
  { key: "postgresql_retrieval", label: "Postgres" },
  { key: "rerank", label: "Rerank" },
];

function timingBreakdown(timings: Record<string, number>) {
  return timingLabels
    .filter((timing) => timings[timing.key] != null)
    .map((timing) => `${timing.label} ${Math.round(timings[timing.key])}`)
    .join(" · ");
}

function ArmBars({ diagnostics }: { diagnostics: RetrievalDiagnostics }) {
  const pool = diagnostics.candidate_counts.fused_pool ?? 0;
  return (
    <div className="lab-diagnostics-arms">
      <p>
        Candidates found per arm
        <small>
          Counts, not ranks. Arms overlap, so these do not sum to the pool.
        </small>
      </p>
      {armLabels.map((arm) => {
        const count = diagnostics.candidate_counts[arm.key] ?? 0;
        const share = pool > 0 ? Math.min(1, count / pool) : 0;
        return (
          <div key={arm.key}>
            <span>{arm.label}</span>
            <i aria-hidden="true">
              <b style={{ width: `${(share * 100).toFixed(1)}%` }} />
            </i>
            {/* "of {pool}", never a bare integer: these sit one panel away from a
                table of per-product ranks, and a lone "2" reads as one. */}
            <strong>{count}<em> of {pool}</em></strong>
          </div>
        );
      })}
    </div>
  );
}

export function RetrievalDiagnosticsStrip({ response }: { response: SearchResponse }) {
  const diagnostics = response.diagnostics;
  if (!diagnostics) return null;

  const topSignals = response.results.find((result) => result.signals?.final_rank === 1)?.signals
    ?? response.results[0]?.signals
    ?? null;
  const pool = diagnostics.candidate_counts.fused_pool ?? 0;
  const breakdown = timingBreakdown(diagnostics.stage_timings_ms);

  return (
    <section className="lab-diagnostics" aria-label="Measured retrieval diagnostics">
      {/* Four figures, not six. "Results shown" and "Requested top-k" repeated the
          Retrieve stage's own "Rows returned" tile verbatim one panel above. */}
      <dl className="lab-diagnostics-figures">
        <div>
          <dt>Query time</dt>
          <dd>{diagnostics.total_latency_ms}<em>ms</em></dd>
          <small>{breakdown || "No stage timings reported"}</small>
        </div>
        <div>
          <dt>Rank 1 fused score</dt>
          <dd className="mono">{topSignals ? topSignals.rrf_score.toFixed(5) : "-"}</dd>
          <small>k = {diagnostics.retrieval_profile.rrf_k}</small>
        </div>
        <div>
          <dt>Reranker</dt>
          <dd className={`lab-diagnostics-status ${diagnostics.rerank_status}`}>
            {diagnostics.rerank_status}
          </dd>
          <small>{diagnostics.rerank_model_id ?? "Not requested for this run"}</small>
        </div>
      </dl>
      <ArmBars diagnostics={diagnostics} />
      {/* The scale caveat is two sentences of prose. In a 150px figure tile it ran
          to five lines and broke the row's rhythm; as the strip's own footnote it
          reads once and applies to every number above it. */}
      {topSignals ? (
        <p className="lab-diagnostics-semantics">{topSignals.score_semantics}</p>
      ) : null}
    </section>
  );
}
