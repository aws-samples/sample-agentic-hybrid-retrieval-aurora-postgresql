import type { RetrievalDiagnostics, SearchResponse } from "../types";

/**
 * The measured band for one retrieval run.
 *
 * Every figure here is read off the response the service just returned. There
 * is no placeholder state and no derived estimate: the strip only renders once
 * a query has actually run, so a participant reading a number can go find the
 * row it came from.
 */

const armLabels: Array<{ key: string; label: string }> = [
  { key: "fts_in_pool", label: "Full-text" },
  { key: "trigram_in_pool", label: "pg_trgm" },
  { key: "semantic_in_pool", label: "Vector" },
];

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
        Candidates per arm
        <small>Arms overlap, so these do not sum to the fused pool.</small>
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
            <strong>{count}</strong>
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
      <dl className="lab-diagnostics-figures">
        <div>
          <dt>Query time</dt>
          <dd>{diagnostics.total_latency_ms}<em>ms</em></dd>
          <small>{breakdown || "No stage timings reported"}</small>
        </div>
        <div>
          <dt>Results shown</dt>
          <dd>{response.results.length}</dd>
          <small>of {pool} fused candidates</small>
        </div>
        <div>
          <dt>Requested top-k</dt>
          <dd>{diagnostics.retrieval_profile.result_limit}</dd>
          <small>RRF k = {diagnostics.retrieval_profile.rrf_k}</small>
        </div>
        <div>
          <dt>Rank 1 RRF score</dt>
          <dd className="mono">{topSignals ? topSignals.rrf_score.toFixed(5) : "-"}</dd>
          <small>{topSignals?.score_semantics ?? "No ranked candidate"}</small>
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
    </section>
  );
}
