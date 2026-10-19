import { useRef, useState } from "react";
import { api } from "../api";
import type {
  RetrievalPlanResponse,
  RetrievalRunResponse,
  SearchResponse,
} from "../types";
import { CodeBlock } from "./CodeBlock";
import { PlaygroundDisclosure } from "./PlaygroundStage";
import { QueryPlanSummary } from "./QueryPlanSummary";

/**
 * The disclosures that read a run back out of Postgres.
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
              <code>mosaic.search_result_event</code>. Ranks and scores were saved
              by the original request. Each candidate’s <code>eligible</code> field
              checks the current catalog against the saved filters.
            </p>
            <div className="retrieval-readout">
              <dl aria-label="Saved search context">
                <div><dt>Recorded at</dt><dd>{event.run.occurred_at}</dd></div>
                <div><dt>PostgreSQL version</dt><dd>{event.run.database_version ?? "Not recorded"}</dd></div>
                <div><dt>pgvector version</dt><dd>{event.run.vector_extension_version ?? "Not recorded"}</dd></div>
                <div><dt>Source revision</dt><dd><code>{event.run.source_revision ?? "Not recorded"}</code>{event.run.source_worktree_dirty === true ? " · includes local changes" : event.run.source_worktree_dirty === false ? " · clean checkout" : " · checkout state not recorded"}</dd></div>
              </dl>
            </div>
            <CodeBlock
              code={JSON.stringify(event, null, 2)}
              label={`search_event_${runId.slice(0, 8)}.json`}
            />
          </>
        )}
      </PlaygroundDisclosure>

      <PlaygroundDisclosure
        key={`plan-${runId}`}
        label="Run EXPLAIN ANALYZE"
        hint="executes search SQL again with current data"
        onOpen={loadPlan}
      >
        <p>Reuses the saved query, filters and search settings with the current SQL
          functions and catalog. A query embedding may be requested from the
          configured model if it is not cached. This captures SQL work only;
          reranking and the Retrieval agent are not run.</p>
        <p>The capture replaces the plan saved on this search record. The original
          candidate ranks stay unchanged. Reopening this panel shows this capture.</p>
        {planError ? (
          <p className="labs-disclosure-error" role="alert">{planError}</p>
        ) : plan === null ? (
          <p role="status">
            {planPending
              ? "Executing EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)."
              : "Open to capture the plan."}
          </p>
        ) : (
          <><QueryPlanSummary plan={plan.plan} /><CodeBlock
            code={JSON.stringify(plan.plan, null, 2)}
            label="explain_analyze.json"
          /></>
        )}
      </PlaygroundDisclosure>
    </>
  );
}
