import { AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import {
  buildRepairEvidence,
  isPlausibleSearchEventId,
  NO_BEFORE_EVENT,
  poolCountText,
  RANK_UNCHANGED_REASSURANCE,
  rankText,
  SUSPICIOUS_GAP_CAUTION,
} from "../repairEvidence";
import { FINAL_LABEL, FUSED_LABEL } from "../retrievalLanguage";
import type { RetrievalRunResponse } from "../types";
import { PlaygroundFigure, PlaygroundFigures } from "./PlaygroundStage";

/**
 * "What did my fix actually change?" for two persisted retrieval events.
 *
 * Lives inside the Playground, not as a fourth numbered stage: it reads state
 * the numbered stages already produce (a `search_event_id`) rather than running
 * its own retrieval, so it is a lens over Stage 01/02's own evidence rather than
 * a fourth thing in the pipeline. It also has nothing to do with the canonical
 * evaluation artifact Stage 04 reads, so it does not belong there either.
 *
 * Both events are fetched fresh from `GET /api/retrieval/events/{id}` -- the same
 * endpoint `PersistedRunDisclosures` uses -- rather than trusting whatever is
 * still in memory from an earlier render, for the same reason that disclosure
 * exists: the receipt should come back out of Postgres.
 */

interface EventFieldState {
  run: RetrievalRunResponse | null;
  error: string;
}

async function loadEvent(rawId: string): Promise<EventFieldState> {
  const id = rawId.trim();
  if (!id) return { run: null, error: "" };
  if (!isPlausibleSearchEventId(id)) {
    return {
      run: null,
      error: `"${id}" doesn't look like a search_event_id -- expected a UUID, `
        + "such as 8c1f2e4a-2b7a-4a5b-9c3d-1a2b3c4d5e6f.",
    };
  }
  try {
    return { run: await api.retrievalEvent(id), error: "" };
  } catch (cause) {
    const message = cause instanceof ApiError && cause.status === 404
      ? `No retrieval event found for ${id}. Check it was pasted in full.`
      : cause instanceof Error
        ? cause.message
        : "That retrieval event could not be read.";
    return { run: null, error: message };
  }
}

export function RepairEvidence({
  latestSearchEventId,
}: {
  /** The most recent run's own id, from whichever numbered stage produced it.
   * Prefills the "after" field so a participant who already has a broken-state
   * "before" saved only has to paste one id. */
  latestSearchEventId: string | null;
}) {
  const [beforeInput, setBeforeInput] = useState("");
  const [afterInput, setAfterInput] = useState(latestSearchEventId ?? "");
  const [beforeRun, setBeforeRun] = useState<RetrievalRunResponse | null>(null);
  const [afterRun, setAfterRun] = useState<RetrievalRunResponse | null>(null);
  const [beforeError, setBeforeError] = useState("");
  const [afterError, setAfterError] = useState("");
  const [pending, setPending] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const compareVersion = useRef(0);

  function invalidateComparison() {
    compareVersion.current += 1;
    setBeforeRun(null);
    setAfterRun(null);
    setBeforeError("");
    setAfterError("");
    setPending(false);
    setAttempted(false);
  }

  // A fresh run landing on the numbered stages above becomes the new "after" by
  // default. This only fires when that id actually changes, so editing the field
  // by hand between runs is never clobbered mid-session.
  useEffect(() => {
    invalidateComparison();
    if (latestSearchEventId) setAfterInput(latestSearchEventId);
  }, [latestSearchEventId]);

  async function compare() {
    const request = ++compareVersion.current;
    const beforeValue = beforeInput.trim();
    const afterValue = afterInput.trim();
    setAttempted(true);
    setPending(true);
    setBeforeRun(null);
    setAfterRun(null);
    setBeforeError("");
    setAfterError("");
    const [afterResult, beforeResult] = await Promise.all([
      afterValue
        ? loadEvent(afterValue)
        : Promise.resolve<EventFieldState>({
          run: null,
          error: "Paste an after search_event_id, or run the pipeline above first.",
        }),
      loadEvent(beforeValue),
    ]);
    if (request !== compareVersion.current) return;
    setAfterRun(afterResult.run);
    setAfterError(afterResult.error);
    setBeforeRun(beforeResult.run);
    setBeforeError(beforeResult.error);
    setPending(false);
  }

  const evidence = useMemo(
    () => (afterRun ? buildRepairEvidence(beforeRun, afterRun) : null),
    [beforeRun, afterRun],
  );

  return (
    <section className="labs-repair" aria-labelledby="labs-repair-title">
      <h3 id="labs-repair-title">Repair evidence</h3>
      <p className="labs-repair-intro">
        Paste two persisted <code>search_event_id</code>s to see what a fix actually
        changed: which arms contributed to the served pool, and where the target
        result sat before and after reranking. Rank alone can look unchanged even
        when the repair worked.
      </p>
      <form
        className="labs-repair-form"
        onSubmit={(event) => {
          event.preventDefault();
          void compare();
        }}
      >
        <label>
          <span>Before (optional)</span>
          <input
            aria-label="Before search_event_id"
            autoComplete="off"
            onChange={(event) => {
              invalidateComparison();
              setBeforeInput(event.target.value);
            }}
            placeholder="from /tmp/typo-recovery.json"
            spellCheck={false}
            type="text"
            value={beforeInput}
          />
        </label>
        <label>
          <span>After</span>
          <input
            aria-label="After search_event_id"
            autoComplete="off"
            onChange={(event) => {
              invalidateComparison();
              setAfterInput(event.target.value);
            }}
            placeholder="most recent run, or paste one"
            spellCheck={false}
            type="text"
            value={afterInput}
          />
        </label>
        <button className="secondary-button" disabled={pending} type="submit">
          {pending ? "Comparing" : "Compare"}
        </button>
      </form>

      {afterError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          <span>{afterError}</span>
        </p>
      ) : null}
      {beforeError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          <span>{beforeError}</span>
        </p>
      ) : null}

      {!attempted ? (
        <p className="labs-repair-hint" role="status">
          Paste the before id you saved while the lab was still broken -- the after
          field already holds your most recent run -- then press Compare.
        </p>
      ) : null}

      {evidence ? (
        evidence.targetProductId === null ? (
          <p className="labs-repair-hint" role="status">
            The after run served no ranked result to anchor this comparison against.
          </p>
        ) : (
          <>
            <p className="labs-repair-target">
              Comparing against the after run&apos;s top result, product #
              {evidence.targetProductId}.
            </p>

            {!evidence.hasBefore ? (
              <p className="labs-repair-no-before" role="status">{NO_BEFORE_EVENT}</p>
            ) : null}

            <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Arm participation delta">
              <table className="labs-rrf-table">
                <thead>
                  <tr>
                    <th scope="col">Arm</th>
                    <th scope="col">In pool, before</th>
                    <th scope="col">In pool, after</th>
                    <th scope="col">Target rank, before</th>
                    <th scope="col">Target rank, after</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.armDeltas.map((delta) => (
                    <tr key={delta.arm}>
                      <th scope="row">
                        {delta.label}
                        <small>{delta.mechanism}</small>
                      </th>
                      <td className="mono">{poolCountText(delta.beforeInPool)}</td>
                      <td className="mono">{delta.afterInPool}</td>
                      <td className="mono">{rankText(delta.beforeTargetRank)}</td>
                      <td className="mono">{rankText(delta.afterTargetRank)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <PlaygroundFigures label="Rank spaces for the target product">
              <PlaygroundFigure
                label={FUSED_LABEL}
                value={`${rankText(evidence.fused.before)} → ${rankText(evidence.fused.after)}`}
                detail="position in the fused candidate pool"
              />
              <PlaygroundFigure
                label={FINAL_LABEL}
                value={`${rankText(evidence.final.before)} → ${rankText(evidence.final.after)}`}
                detail="position in the returned, served rows"
                tone={evidence.afterGap.suspicious ? "warn" : "plain"}
              />
            </PlaygroundFigures>

            {evidence.rankUnchanged ? (
              <p className="labs-repair-reassurance" role="note">
                {RANK_UNCHANGED_REASSURANCE}
              </p>
            ) : null}

            {evidence.afterGap.suspicious ? (
              <p className="labs-repair-caution" role="alert">
                <AlertTriangle aria-hidden="true" size={15} />
                <span>{SUSPICIOUS_GAP_CAUTION}</span>
              </p>
            ) : null}
          </>
        )
      ) : null}
    </section>
  );
}
