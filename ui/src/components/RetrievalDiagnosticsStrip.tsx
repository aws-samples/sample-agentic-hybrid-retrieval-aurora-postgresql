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

/**
 * Display names for the stages the service is known to time, in reading order.
 *
 * This is a naming table, not a filter. The previous version listed three keys
 * and rendered only those, so `coverage` and `result_persistence` -- both
 * measured, both in the response -- were dropped on the floor: a fifth of the
 * run's instrumented time was missing from a strip whose own contract is that
 * every figure is read off the response. A stage the service adds tomorrow
 * would have vanished the same silent way, which is the part that made it a
 * defect rather than an omission.
 */
const timingLabels: Record<string, string> = {
  embedding: "Embed",
  postgresql_retrieval: "Postgres",
  rerank: "Rerank",
  coverage: "Coverage",
  result_persistence: "Persist",
};

const timingOrder = Object.keys(timingLabels);

/** `postgresql_retrieval` -> `Postgresql retrieval`, for a stage added later. */
function timingLabel(key: string): string {
  const known = timingLabels[key];
  if (known) return known;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A measured stage never reads as zero.
 *
 * `_embed_query` in service/retrieval.py keeps a 256-entry LRU so a repeated
 * query re-uses its first vector, and the timer wraps the lookup rather than
 * the model call. A cache hit measures ~0.005 ms, and rounding printed that as
 * `Embed 0` -- on the Lab 1 anchor query, which a participant has usually
 * already run in Shop, so the embedding step advertised itself as free on the
 * one surface that exists to show what retrieval costs. `<1` is what was
 * actually measured and claims nothing the run did not report.
 */
function timingValue(milliseconds: number): string {
  const rounded = Math.round(milliseconds);
  return rounded === 0 && milliseconds > 0 ? "<1" : String(rounded);
}

function timingBreakdown(timings: Record<string, number>) {
  const keys = Object.keys(timings).sort((left, right) => {
    const leftIndex = timingOrder.indexOf(left);
    const rightIndex = timingOrder.indexOf(right);
    // An unknown stage sorts after every known one rather than to the front.
    return (
      (leftIndex === -1 ? timingOrder.length : leftIndex) -
      (rightIndex === -1 ? timingOrder.length : rightIndex)
    );
  });
  return keys
    .filter((key) => timings[key] != null)
    .map((key) => `${timingLabel(key)} ${timingValue(timings[key])}`)
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
          {/* Said once, for the same reason the arm bars say "these do not sum to
              the pool": the figure above is the wall clock the caller waited on,
              and the stages below are the spans the service instrumented inside
              it. They are close but never equal, and a participant who adds them
              up should find that out here rather than conclude a number lied. */}
          <small>
            {breakdown || "No stage timings reported"}
            {breakdown ? (
              <span className="lab-diagnostics-timing-note">
                Instrumented stages, in milliseconds. They sit inside the total
                and do not sum to it.
              </span>
            ) : null}
          </small>
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
