import { useRef, useState } from "react";
import { api } from "../api";
import { armLanguage } from "../retrievalLanguage";
import type {
  ProductSummary,
  RetrievalPlanResponse,
  RetrievalRunResponse,
  SearchResponse,
} from "../types";
import { CodeBlock } from "./CodeBlock";
import { PlaygroundDisclosure } from "./PlaygroundStage";

/**
 * The three disclosures that read a run back out of Postgres, plus the fusion
 * arithmetic.
 *
 * `POST /api/search` and `GET /api/retrieval/events/{id}` have existed since the
 * service was written and nothing in the browser had ever called the second one,
 * so every number on the retrieval surface was the response the page was already
 * holding. That is fine as a display and useless as proof: a participant asking
 * "is that what Aurora actually did" had no way to check. These read
 * `mosaic.search_event`, `mosaic.search_result_event`, and EXPLAIN ANALYZE over
 * the run's own SQL path.
 */

/**
 * Reciprocal rank fusion, shown as arithmetic rather than as a score.
 *
 * Lab 2 replaces `1 / (k + source_rank)` with `1 / (k + 1)`, so every arm
 * contributes as if it held rank 1 and within-arm order disappears. That defect is
 * invisible in a fused score and obvious in a column of contributions that are all
 * the same number, which is why this table prints the operands and not just the
 * result. `rrf_k` comes from the response's own retrieval profile — there is no
 * local default, because inventing one would let this table state a k the run did
 * not use.
 */
export function RrfMath({ response }: { response: SearchResponse }) {
  const rrfK = response.diagnostics?.retrieval_profile.rrf_k;
  const rows = response.results.filter((product) => product.signals);
  if (rrfK == null || !rows.length) {
    return (
      <p>
        This run reported no <code>rrf_k</code>, so the arithmetic behind its fused
        scores cannot be shown without guessing at one.
      </p>
    );
  }
  return (
    <>
      <p className="labs-rrf-formula">
        <code>contribution = 1 / (k + rank_in_that_arm)</code>, summed over the arms
        that found the row. <code>k = {rrfK}</code> for this run.
      </p>
      <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Fusion arithmetic">
        <table className="labs-rrf-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              {armLanguage.map((arm) => (
                <th key={arm.key} scope="col">{arm.label}</th>
              ))}
              <th scope="col">Sum</th>
              <th scope="col">Reported rrf_score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((product) => {
              const signals = product.signals!;
              const parts = armLanguage.map((arm) => signals[arm.key]);
              const sum = parts.reduce(
                (total, part) => total + (part.rrf_contribution ?? 0),
                0,
              );
              // 1e-9, the same tolerance labOutcome uses to decide whether the
              // contributions the database reported add up to the score it
              // reported. A mismatch is a defect in fusion, not a rounding
              // artifact.
              const agrees = Math.abs(sum - signals.rrf_score) <= 1e-9;
              return (
                <tr key={product.product_id}>
                  <th scope="row">{product.model}</th>
                  {parts.map((part, index) => (
                    <td key={armLanguage[index].key}>
                      {part.rank === null ? (
                        <em>not found</em>
                      ) : (
                        <>
                          <span>1 / ({rrfK} + {part.rank})</span>
                          <b>{part.rrf_contribution?.toFixed(6) ?? "-"}</b>
                        </>
                      )}
                    </td>
                  ))}
                  <td className="mono">{sum.toFixed(6)}</td>
                  <td className={agrees ? "mono" : "mono labs-rrf-mismatch"}>
                    {signals.rrf_score.toFixed(6)}
                    {agrees ? null : <small>does not match the sum</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** The returned rows, as ranks rather than prose. */
export function CandidateRows({ products }: { products: ProductSummary[] }) {
  const rows = products.filter((product) => product.signals);
  return (
    <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Candidate rows">
      <table className="labs-rrf-table">
        <thead>
          <tr>
            {/* The leading column is the final position, so a "Final position"
                column at the far right printed the same number twice. */}
            <th scope="col">Final</th>
            <th scope="col">Product</th>
            <th scope="col">SKU</th>
            {armLanguage.map((arm) => (
              <th key={arm.key} scope="col">{arm.label}</th>
            ))}
            <th scope="col">Before reranking</th>
            <th scope="col">Rerank score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((product) => {
            const signals = product.signals!;
            return (
              <tr key={product.product_id}>
                <td className="mono">{signals.final_rank}</td>
                <th scope="row">{product.model}</th>
                <td className="mono">{product.sku}</td>
                {armLanguage.map((arm) => (
                  <td className="mono" key={arm.key}>
                    {signals[arm.key].rank === null
                      ? <em>not found</em>
                      : `#${signals[arm.key].rank}`}
                  </td>
                ))}
                <td className="mono">#{signals.pre_rerank_rank}</td>
                <td className="mono">{signals.rerank_score?.toFixed(4) ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The persisted event and its EXPLAIN plan, fetched on first open.
 *
 * The plan capture is a POST: it runs `EXPLAIN (ANALYZE, FORMAT JSON)` against the
 * run's own SQL path and persists the result, so it is deliberately behind a click
 * rather than fired on load.
 */
export function PersistedRunDisclosures({ response }: { response: SearchResponse }) {
  const runId = response.search_event_id;
  const currentRunId = useRef(runId);
  const eventRequest = useRef(0);
  const planRequest = useRef(0);
  const [eventState, setEventState] = useState<{
    runId: string;
    value: RetrievalRunResponse;
  } | null>(null);
  const [eventErrorState, setEventErrorState] = useState<{
    runId: string;
    message: string;
  } | null>(null);
  const [eventPendingState, setEventPendingState] = useState<{
    runId: string;
    request: number;
  } | null>(null);
  const [planState, setPlanState] = useState<{
    runId: string;
    value: RetrievalPlanResponse;
  } | null>(null);
  const [planErrorState, setPlanErrorState] = useState<{
    runId: string;
    message: string;
  } | null>(null);
  const [planPendingState, setPlanPendingState] = useState<{
    runId: string;
    request: number;
  } | null>(null);

  currentRunId.current = runId;
  const event = eventState?.runId === runId ? eventState.value : null;
  const eventError =
    eventErrorState?.runId === runId ? eventErrorState.message : "";
  const eventPending =
    eventPendingState?.runId === runId
    && eventPendingState.request === eventRequest.current;
  const plan = planState?.runId === runId ? planState.value : null;
  const planError =
    planErrorState?.runId === runId ? planErrorState.message : "";
  const planPending =
    planPendingState?.runId === runId
    && planPendingState.request === planRequest.current;

  function loadEvent() {
    if (event || eventPending) return;
    const request = ++eventRequest.current;
    const requestedRunId = runId;
    setEventErrorState(null);
    setEventPendingState({ runId: requestedRunId, request });
    api
      .retrievalEvent(requestedRunId)
      .then((value) => {
        if (
          request === eventRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setEventState({ runId: requestedRunId, value });
        }
      })
      .catch((cause: unknown) => {
        if (
          request === eventRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setEventErrorState({
            runId: requestedRunId,
            message: cause instanceof Error
              ? cause.message
              : "This run's persisted event could not be read",
          });
        }
      })
      .finally(() => {
        if (
          request === eventRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setEventPendingState(null);
        }
      });
  }

  function loadPlan() {
    if (plan || planPending) return;
    const request = ++planRequest.current;
    const requestedRunId = runId;
    setPlanErrorState(null);
    setPlanPendingState({ runId: requestedRunId, request });
    api
      .retrievalPlan(requestedRunId)
      .then((value) => {
        if (
          request === planRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setPlanState({ runId: requestedRunId, value });
        }
      })
      .catch((cause: unknown) => {
        if (
          request === planRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setPlanErrorState({
            runId: requestedRunId,
            message: cause instanceof Error
              ? cause.message
              : "EXPLAIN capture failed",
          });
        }
      })
      .finally(() => {
        if (
          request === planRequest.current
          && requestedRunId === currentRunId.current
        ) {
          setPlanPendingState(null);
        }
      });
  }

  return (
    <>
      <PlaygroundDisclosure
        key={`event-${runId}`}
        label="View retrieval event"
        hint={`run ${runId.slice(0, 8)}, read back from Postgres`}
        onOpen={loadEvent}
      >
        {eventError ? (
          <p className="labs-disclosure-error" role="alert">{eventError}</p>
        ) : event === null ? (
          <p role="status">Reading mosaic.search_event.</p>
        ) : (
          <>
            <p className="labs-contract-note">
              {event.candidates.length} rows in{" "}
              <code>mosaic.search_result_event</code>, written by the request that
              produced what is on screen. Everything above came from the same two
              tables.
            </p>
            <CodeBlock
              code={JSON.stringify(event, null, 2)}
              label={`search_event_${runId.slice(0, 8)}.json`}
            />
          </>
        )}
      </PlaygroundDisclosure>

      <PlaygroundDisclosure
        key={`plan-${runId}`}
        label="View EXPLAIN"
        hint="runs EXPLAIN ANALYZE on this run's SQL"
        onOpen={loadPlan}
      >
        {planError ? (
          <p className="labs-disclosure-error" role="alert">{planError}</p>
        ) : plan === null ? (
          <p role="status">
            {planPending
              ? "Capturing EXPLAIN (ANALYZE, FORMAT JSON) for this event."
              : "Open to capture the plan."}
          </p>
        ) : (
          <CodeBlock
            code={JSON.stringify(plan.plan, null, 2)}
            label="explain_analyze.json"
          />
        )}
      </PlaygroundDisclosure>
    </>
  );
}
