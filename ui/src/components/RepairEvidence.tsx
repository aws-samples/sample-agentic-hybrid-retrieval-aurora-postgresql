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
  baselineSearchEventId,
  latestSearchEventId,
}: {
  /** The run the Playground has pinned as this mission's starting point: the
   * carried-over Shop run, the first run of a scenario, or whatever the
   * participant re-pinned. Compared against the latest run automatically, which
   * is what removes the two-UUIDs-from-a-saved-file step this panel used to
   * require. */
  baselineSearchEventId: string | null;
  /** The most recent run's own id, from whichever numbered stage produced it.
   * Prefills the "after" field so a participant who already has a broken-state
   * "before" saved only has to paste one id. */
  latestSearchEventId: string | null;
}) {
  const [beforeInput, setBeforeInput] = useState(baselineSearchEventId ?? "");
  const [afterInput, setAfterInput] = useState(latestSearchEventId ?? "");
  const [beforeRun, setBeforeRun] = useState<RetrievalRunResponse | null>(null);
  const [afterRun, setAfterRun] = useState<RetrievalRunResponse | null>(null);
  const [beforeError, setBeforeError] = useState("");
  const [afterError, setAfterError] = useState("");
  const [pending, setPending] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [compared, setCompared] = useState<{ before: string; after: string } | null>(null);
  const compareVersion = useRef(0);

  function invalidateComparison() {
    compareVersion.current += 1;
    setBeforeRun(null);
    setAfterRun(null);
    setBeforeError("");
    setAfterError("");
    setPending(false);
    setAttempted(false);
    setCompared(null);
  }

  // A fresh run landing on the numbered stages above becomes the new "after" by
  // default, and the pinned baseline becomes the new "before". This only fires
  // when one of those ids actually changes, so editing a field by hand between
  // runs is never clobbered mid-session.
  //
  // Two known ids are compared without being asked. The participant already
  // decided what to compare when they pinned the baseline and ran the pipeline
  // again; making them re-state it by pasting both ids back in was the step that
  // sent this panel's own instructions to a file on disk. Ids that are not
  // shaped like event ids are left alone: an automatic comparison must not raise
  // a paste error for something nobody pasted.
  useEffect(() => {
    invalidateComparison();
    if (latestSearchEventId) setAfterInput(latestSearchEventId);
    if (baselineSearchEventId) setBeforeInput(baselineSearchEventId);
    if (
      baselineSearchEventId
      && latestSearchEventId
      && baselineSearchEventId !== latestSearchEventId
      && isPlausibleSearchEventId(baselineSearchEventId)
      && isPlausibleSearchEventId(latestSearchEventId)
    ) {
      void compareIds(baselineSearchEventId, latestSearchEventId);
    }
  }, [baselineSearchEventId, latestSearchEventId]);

  async function compareIds(before: string, after: string) {
    const request = ++compareVersion.current;
    const beforeValue = before.trim();
    const afterValue = after.trim();
    setAttempted(true);
    setCompared(null);
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
    // Claimed only once both runs are in hand. Announcing the pair before the
    // reads resolve put "Comparing baseline X against Y" directly above the
    // alert saying one of them could not be read.
    setCompared(
      beforeValue && afterValue && !beforeResult.error && !afterResult.error
        ? { before: beforeValue, after: afterValue }
        : null,
    );
    setPending(false);
  }

  const compare = () => compareIds(beforeInput, afterInput);

  const evidence = useMemo(
    () => (afterRun ? buildRepairEvidence(beforeRun, afterRun) : null),
    [beforeRun, afterRun],
  );

  return (
    <section className="labs-repair" aria-labelledby="labs-repair-title">
      <div className="labs-repair-content">
        <h3 id="labs-repair-title">Repair evidence</h3>
        <p className="labs-repair-intro">
          What a fix actually changed, read back from two persisted runs: which arms
          contributed to the served pool, and where the target result sat before and
          after reranking. Rank alone can look unchanged even when the repair worked.
        </p>
        {compared ? (
          <p className="labs-repair-pair">
            Comparing baseline <code>{compared.before}</code> against{" "}
            <code>{compared.after}</code>.
          </p>
        ) : null}
        <details className="labs-repair-other">
          <summary>Compare other runs</summary>
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
                placeholder="paste a search_event_id"
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
        </details>

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
          {/* A carried arrival pins a baseline before anything has been run, so
              telling that participant to pin one names a step they have already
              taken and hides the one thing still missing: a second run. */}
          {baselineSearchEventId && baselineSearchEventId === latestSearchEventId
            ? "Run the pipeline to compare against the pinned baseline."
            : "Pin a baseline run above, then run the pipeline again: this panel "
              + "compares the two on its own."}
          {" "}
          To diff runs it does not already hold, open Compare other runs and paste
          both ids.
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
      </div>
    </section>
  );
}
