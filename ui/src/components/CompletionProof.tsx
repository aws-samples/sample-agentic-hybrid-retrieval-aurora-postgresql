import { AlertTriangle, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { coreMosaicLabs } from "../labMissions";
import type { CompletionProofResponse } from "../types";
import { shortEventId } from "./RunSummary";

/**
 * "Am I finished?", answered against Aurora rather than against the screen.
 *
 * Every other surface in the Playground reports what one run did. None of them
 * answers the question a participant actually has at the end of a lab, and the
 * two ways they tried to are both wrong: a green outcome banner grades the run
 * on screen, and the release baseline below grades the maintainers' tree. This
 * posts each lab's own acceptance conditions to `POST /api/labs/{id}/proof` and
 * reports the verdict the service returns.
 *
 * Three properties it has to keep:
 *
 *   1. Labs 1 and 2 need nothing from the caller -- the service re-runs their
 *      mission through the same path `POST /api/search` uses. Lab 3 grades a
 *      persisted turn, so with no run to name it says which stage produces one
 *      and posts nothing, rather than spending a request to be told that.
 *   2. Every failed check is shown with the falsifier the service served next
 *      to it. A verdict without the condition that would have overturned it is
 *      an assertion, not evidence.
 *   3. An unreachable cluster is a problem with the room. Reporting a 503 as a
 *      failed lab sends a participant to edit SQL that was already correct.
 */

const LAB_IDS = [1, 2, 3] as const;

type LabId = (typeof LAB_IDS)[number];

/** What Lab 3 needs before it can be graded, named as the stage that makes it. */
const LAB_3_PREREQUISITE = "Run the agent in 03 first";

type LabOutcome =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "skipped"; reason: string }
  | { kind: "proved"; proof: CompletionProofResponse }
  | { kind: "unavailable"; message: string };

type Outcomes = Record<LabId, LabOutcome>;

const IDLE_OUTCOMES: Outcomes = { 1: { kind: "idle" }, 2: { kind: "idle" }, 3: { kind: "idle" } };

/** `not_applicable` is a sentence, not an identifier, once it reaches a badge. */
function readableState(state: string): string {
  return state.replaceAll("_", " ");
}

/**
 * Why the proof could not run, in the terms a room problem has to use.
 *
 * Never phrased as a lab verdict: the service already distinguishes a stale
 * function (a verdict) from an unreachable cluster (a 503), and this side must
 * not collapse them back together.
 */
function environmentMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 404) {
      return `This build's API serves no proof for that lab (HTTP 404). ${cause.message}`;
    }
    // The service answered and said what was wrong, in its own words.
    return cause.message;
  }
  // Nothing answered: the API is not running, the proxy refused, or the tab is
  // offline. `fetch` raises a bare "Failed to fetch", which names neither the
  // service that failed to answer nor the fact that no lab was graded.
  const detail = cause instanceof Error ? cause.message : String(cause);
  return `The completion proof could not reach the Mosaic API (${detail}).`;
}

function statusLabel(outcome: LabOutcome): string {
  if (outcome.kind === "proved") return outcome.proof.status === "pass" ? "PASS" : "FAIL";
  if (outcome.kind === "running") return "Running";
  if (outcome.kind === "unavailable") return "Could not run";
  if (outcome.kind === "skipped") return "Needs 03";
  return "Not run yet";
}

function statusTone(outcome: LabOutcome): string {
  if (outcome.kind === "proved") return outcome.proof.status === "pass" ? "is-pass" : "is-fail";
  if (outcome.kind === "unavailable") return "is-blocked";
  return "is-quiet";
}

/** The receipts a proof produced, in the short form the run summary uses. */
function ProofEvidence({ proof }: { proof: CompletionProofResponse }) {
  const { agent_run_id: agentRunId, evidence_ids: evidenceIds } = proof.evidence;
  return (
    <ul className="labs-proof-evidence">
      {proof.evidence.search_event_ids.map((eventId) => (
        <li key={eventId}>
          search event <code>{shortEventId(eventId)}</code>
        </li>
      ))}
      {agentRunId ? (
        <li>
          agent run <code>{shortEventId(agentRunId)}</code>
        </li>
      ) : null}
      {evidenceIds.length ? (
        <li>
          evidence rows <code>{evidenceIds.join(", ")}</code>
        </li>
      ) : null}
    </ul>
  );
}

/**
 * Why a lab failed when none of its checks did, as the next thing to do.
 *
 * `service/lab_proof.py` fails a lab whose source still holds the broken block
 * or whose database is stale *regardless* of the checks, so the taught
 * "repaired the file, never re-applied it" case arrives here as FAIL with
 * every check green and nothing under it to act on.
 */
function failureReason(proof: CompletionProofResponse): string | null {
  if (proof.source_state === "broken") {
    // Named before the database: applying an unrepaired file installs the
    // broken function, so the file is the first thing to fix.
    return "The source file still holds the broken block."
      + " Apply the repair in Code Editor.";
  }
  if (proof.database_state === "stale") {
    return "The source file is repaired but the database still holds the old"
      + " function. Run make db-apply-search-functions.";
  }
  return null;
}

function ProofDetail({ proof }: { proof: CompletionProofResponse }) {
  const failed = proof.checks.filter((check) => !check.passed);
  const reason = proof.status === "fail" && !failed.length
    ? failureReason(proof)
    : null;
  return (
    <>
      {/* Three facts, never one: the checks held, the file is repaired, and
          Aurora holds that repair. A pass on the first two alone is a repaired
          file in front of an unrepaired cluster. */}
      <p className="labs-proof-states">
        <span>source {readableState(proof.source_state)}</span>
        <span>database {readableState(proof.database_state)}</span>
        <span>
          {proof.checks.length - failed.length} of {proof.checks.length} checks passed
        </span>
        <span>{proof.duration_ms} ms</span>
      </p>
      {reason ? <p className="labs-proof-note">{reason}</p> : null}
      {failed.length ? (
        <ul className="labs-proof-checks">
          {failed.map((check) => (
            <li key={check.name}>
              <code>{check.name}</code>
              <b>{check.detail}</b>
              <small>fails when: {check.falsifier}</small>
            </li>
          ))}
        </ul>
      ) : null}
      {/* Receipts belong to a pass. Event ids under a FAIL read as evidence
          the lab is finished. */}
      {proof.status === "pass" ? <ProofEvidence proof={proof} /> : null}
    </>
  );
}

function LabProofRow({
  active,
  labId,
  outcome,
}: {
  active: boolean;
  labId: LabId;
  outcome: LabOutcome;
}) {
  return (
    <li
      className="labs-proof-lab"
      data-active={active ? "true" : undefined}
      data-testid={`completion-proof-lab-${labId}`}
    >
      <header>
        {/* The manifest title already carries the lab number, so it is the
            whole label here rather than a subtitle under a repeated one. */}
        <b>{coreMosaicLabs[labId - 1]?.title ?? `Lab ${labId}`}</b>
        <em className={`labs-proof-status ${statusTone(outcome)}`}>
          {statusLabel(outcome)}
        </em>
      </header>
      {outcome.kind === "proved" ? <ProofDetail proof={outcome.proof} /> : null}
      {/* The prerequisite is an instruction, so it is set as one rather than
          shouted from the status badge next to PASS and FAIL. */}
      {outcome.kind === "skipped" ? (
        <p className="labs-proof-note">{outcome.reason}.</p>
      ) : null}
      {outcome.kind === "unavailable" ? (
        <p className="labs-proof-blocked" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          {outcome.message}
        </p>
      ) : null}
    </li>
  );
}

interface CompletionProofProps {
  /** The lab the page is currently on, marked so the reader can find it. */
  activeLab: LabId;
  /** The latest agent run from stage 03, which is all Lab 3 can be graded on. */
  agentRunId: string | null;
  /** Called once every proof in a press has settled, pass or fail. */
  onFinished?: () => void;
}

export function CompletionProof({
  activeLab,
  agentRunId,
  onFinished,
}: CompletionProofProps) {
  const [outcomes, setOutcomes] = useState<Outcomes>(IDLE_OUTCOMES);
  const [running, setRunning] = useState(false);
  /**
   * Whether this block is still on the page. The presses are sequential and
   * each one waits on a real retrieval, so a participant can leave mid-run: the
   * loop then has to stop rather than keep spending searches on the workshop
   * cluster and announcing a finish to a page that is gone.
   */
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const record = (labId: LabId, outcome: LabOutcome) => {
    if (!mounted.current) return;
    setOutcomes((current) => ({ ...current, [labId]: outcome }));
  };

  /**
   * Read rather than stored, so clearing the agent run cannot leave a Lab 3
   * verdict on screen that no run on this page supports.
   */
  const outcomeFor = (labId: LabId): LabOutcome =>
    labId === 3 && !agentRunId
      ? { kind: "skipped", reason: LAB_3_PREREQUISITE }
      : outcomes[labId];

  /**
   * One lab at a time. Labs 1 and 2 each run a real search (Lab 2 runs two), so
   * firing all three at once would put three concurrent retrievals on one
   * workshop cluster to save a second the participant is not waiting on.
   */
  async function runProofs() {
    if (running) return;
    setRunning(true);
    setOutcomes(IDLE_OUTCOMES);
    let proved = false;
    for (const labId of LAB_IDS) {
      if (!mounted.current) return;
      if (labId === 3 && !agentRunId) continue;
      record(labId, { kind: "running" });
      try {
        const proof = await api.labProof(labId, {
          agent_run_id: labId === 3 ? agentRunId : null,
        });
        record(labId, { kind: "proved", proof });
        proved = true;
      } catch (cause) {
        record(labId, { kind: "unavailable", message: environmentMessage(cause) });
      }
    }
    if (!mounted.current) return;
    setRunning(false);
    // Only when something actually came back. The release baseline below
    // re-reads on this and drops what it is showing if that read fails, so a
    // press that reached nothing must not blank a baseline that is already on
    // screen.
    if (proved) onFinished?.();
  }

  return (
    <section aria-labelledby="labs-proof-title" className="labs-completion-proof">
      <header className="labs-proof-header">
        <h3 id="labs-proof-title">Completion proof</h3>
        <button
          aria-busy={running}
          className="primary-button"
          disabled={running}
          onClick={() => void runProofs()}
          type="button"
        >
          {running ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <ShieldCheck aria-hidden="true" size={17} />
          )}
          {running ? "Running completion proof" : "Run completion proof"}
        </button>
      </header>
      <p className="labs-proof-intro">
        Labs 1 and 2 re-run their mission through the same search path Shop uses,
        so each press costs a real retrieval. Lab 3 grades the agent run stage 03
        already persisted and spends no new turn. Every check is served with the
        condition that would have failed it.
      </p>
      <ul className="labs-proof-labs">
        {LAB_IDS.map((labId) => (
          <LabProofRow
            active={labId === activeLab}
            key={labId}
            labId={labId}
            outcome={outcomeFor(labId)}
          />
        ))}
      </ul>
    </section>
  );
}
