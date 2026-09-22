import { AlertTriangle } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError, api } from "../api";
import {
  candidatesFromPersistedPool,
  candidatesFromResults,
  findFusionDefectCase,
  findTieCollapseExample,
  FUSION_DEFECT_TEACHING_LINE,
  fusedToFinalGap,
  SUSPICIOUS_GAP_CAUTION,
  type FusionDefectCandidate,
  type FusionDefectTieCollapse,
} from "../fusionDefect";
import { armLabel, armLanguage, FINAL_LABEL, FUSED_LABEL } from "../retrievalLanguage";
import type { RetrievalRunResponse, SearchResponse } from "../types";
import { PlaygroundDisclosure } from "./PlaygroundStage";
import "../fusion-defect-lens.css";

// Calculated comparisons share the saved source ranks, so a changed request
// cannot be mistaken for evidence that the fusion formula was repaired.
function armCells(candidate: FusionDefectCandidate) {
  return candidate.arms.map((arm) => (
    <td className="mono" key={arm.arm}>
      {arm.sourceRank === null ? (
        <em>not found</em>
      ) : (
        <>
          <span>Source rank #{arm.sourceRank}</span>
          <b><span className="labs-fusion-value-label">Correct</span> {arm.expected?.toFixed(6)}</b>
          <em className={arm.sourceRank === 1 ? "" : "labs-rrf-mismatch"}>
            <span className="labs-fusion-value-label">Collapsed</span> {arm.broken?.toFixed(6)}
          </em>
        </>
      )}
    </td>
  ));
}

function ArithmeticHead() {
  return (
    <thead>
      <tr className="labs-fusion-column-groups">
        <th scope="col" rowSpan={2}>Product</th>
        <th scope="colgroup" colSpan={armLanguage.length}>Calculated contributions</th>
        <th scope="colgroup" colSpan={2}>Recorded positions</th>
      </tr>
      <tr>
        {armLanguage.map((arm) => <th key={arm.key} scope="col">{arm.label}</th>)}
        <th scope="col">{FUSED_LABEL}</th>
        <th scope="col">{FINAL_LABEL}</th>
      </tr>
    </thead>
  );
}

function CandidateRow({
  candidate,
  highlight,
}: {
  candidate: FusionDefectCandidate;
  highlight?: string;
}) {
  const { gap, suspicious } = fusedToFinalGap(candidate);
  return (
    <tr>
      <th scope="row">
        {candidate.title}
        {highlight ? <small>{highlight}</small> : null}
      </th>
      {armCells(candidate)}
      <td className="mono">#{candidate.fusedRank}</td>
      <td className={suspicious ? "mono labs-rrf-mismatch" : "mono"}>
        #{candidate.finalRank}
        {suspicious ? <small>+{gap} vs fused</small> : null}
      </td>
    </tr>
  );
}

function TieCollapseExample({ tie }: { tie: FusionDefectTieCollapse }) {
  return (
    <>
      <p className="labs-contract-note">
        {tie.tieGroupSize} of this run's {tie.poolSize} pooled candidates were found by
        the same number of search methods. The collapsed formula gives each a score
        of <code>{tie.first.brokenScore.toFixed(6)}</code>, then the SQL tie-break
        orders them by product ID. For this pair, that calculated order differs
        from the saved order below.
      </p>
      <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Tie-collapse arithmetic">
        <table className="labs-rrf-table">
          <ArithmeticHead />
          <tbody>
            <CandidateRow
              candidate={tie.first.candidate}
              highlight={`Calculated collapsed rank #${tie.first.brokenRank}`}
            />
            <CandidateRow
              candidate={tie.second.candidate}
              highlight={`Calculated collapsed rank #${tie.second.brokenRank}`}
            />
          </tbody>
        </table>
      </div>
      <p className="labs-teaching-line">
        Across these {tie.poolSize} saved candidates, {tie.invertedPairs} pairs
        change order under the collapsed calculation. This comparison does not
        run retrieval again or establish which candidates a fresh run would admit.
      </p>
    </>
  );
}

export function FusionDefectLens({ response }: { response: SearchResponse }) {
  const runId = response.search_event_id;
  const currentRunId = useRef(runId);
  const eventRequest = useRef(0);
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

  currentRunId.current = runId;
  const event = eventState?.runId === runId ? eventState.value : null;
  const eventError =
    eventErrorState?.runId === runId ? eventErrorState.message : "";
  const eventPending =
    eventPendingState?.runId === runId
    && eventPendingState.request === eventRequest.current;

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
            message: cause instanceof ApiError && cause.status === 404
              ? "This run's persisted pool was not found."
              : cause instanceof Error
                ? cause.message
                : "This run's persisted pool could not be read",
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

  const rrfK = response.diagnostics?.retrieval_profile.rrf_k;
  const fusedLimit = response.diagnostics?.retrieval_profile.fused_limit;

  if (rrfK == null) {
    return (
      <p>
        This run reported no <code>rrf_k</code>, so the two formulas cannot be
        compared without guessing at one.
      </p>
    );
  }

  const rows = candidatesFromResults(response.results, rrfK);
  const poolRows = event ? candidatesFromPersistedPool(event.candidates, rrfK) : null;
  const poolTie = poolRows ? findTieCollapseExample(poolRows) : null;
  const inversion = poolRows ? findFusionDefectCase(poolRows) : null;

  return (
    <div className="labs-fusion-defect">
      <p className="labs-contract-note">
        Compare two formulas using this run's source ranks. Contributions below
        are calculated; before-reranking and final positions come from the saved
        run. This is not a before-and-after pair of requests.
      </p>
      <dl className="labs-fusion-formulas">
        <div>
          <dt>Correct formula</dt>
          <dd><code>1 / (rrf_k + source_rank)</code><span>Each position contributes different credit.</span></dd>
        </div>
        <div>
          <dt>Collapsed formula</dt>
          <dd><code>1 / (rrf_k + 1)</code><span>Every position contributes as rank 1.</span></dd>
        </div>
      </dl>
      <p className="labs-fusion-settings">
        Saved settings: <code>rrf_k = {rrfK}</code>
        {fusedLimit == null ? null : <><span aria-hidden="true"> · </span><code>fused_limit = {fusedLimit}</code></>}
      </p>
      <p className="labs-contract-note">
        With the collapsed formula, candidates found by the same number of
        methods tie. SQL breaks those ties by product ID. A correct-looking
        winner can remain first even while lower positions lose their meaning.
      </p>

      <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Fusion defect arithmetic">
        <table className="labs-rrf-table">
          <caption className="sr-only">Source ranks are recorded. Correct and collapsed contributions are calculated from those same ranks.</caption>
          <ArithmeticHead />
          <tbody>
            {rows.map((candidate) => (
              <CandidateRow candidate={candidate} key={candidate.productId} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="labs-fusion-reading-note">Compare the two contributions within a method. Rank 1 receives equal credit under both formulas. Scroll across the table to inspect every method and the recorded positions.</p>

      {eventError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          <span>{eventError}</span>
        </p>
      ) : null}

      <PlaygroundDisclosure
        key={`fusion-pool-${runId}`}
        label="Check this run's full fused pool for the fusion defect"
        hint="compare formulas across the saved candidates"
        onOpen={loadEvent}
      >
        {eventError ? null : poolRows === null ? (
          <p role="status">Loading the saved candidate list…</p>
        ) : (
          <>
            {poolTie ? (
              <TieCollapseExample tie={poolTie} />
            ) : (
              <p className="labs-contract-note">No pair in the largest tied group reverses the saved order. This does not prove the formula is correct; compare the per-method contributions above.</p>
            )}

            {inversion === null ? (
              <p className="labs-contract-note">No recorded pair meets the additional check: a product ranked first by one method sitting below a multi-method competitor whose correct contribution sum is lower. A rank flip is not required to prove the arithmetic defect.</p>
            ) : (
              <>
                <p className="labs-contract-note">
                  Product #{inversion.competitor.productId} sits at fused rank #
                  {inversion.competitor.fusedRank}, ahead of product #{inversion.target.productId}
                  {" "}at fused rank #{inversion.target.fusedRank}. Product #{inversion.target.productId} is rank #1
                  in {armLabel[inversion.targetArm]}, product #{inversion.competitor.productId}
                  &apos;s worst source position is #{inversion.competitorWorstRank} in
                  {" "}{armLabel[inversion.competitorArm]}. Summing the correct contributions
                  puts the target ahead of the competitor, reversing their recorded
                  fused order. Inspect the installed formula and the actual contributions
                  before attributing that difference to the Lab 2 defect.
                </p>

                <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Competitor and target arithmetic">
                  <table className="labs-rrf-table">
                    <ArithmeticHead />
                    <tbody>
                      <CandidateRow candidate={inversion.competitor} highlight="competitor" />
                      <CandidateRow candidate={inversion.target} highlight="rank-1 target" />
                    </tbody>
                  </table>
                </div>

                {fusedToFinalGap(inversion.competitor).suspicious
                  || fusedToFinalGap(inversion.target).suspicious ? (
                    <p className="labs-repair-caution" role="alert">
                      <AlertTriangle aria-hidden="true" size={15} />
                      <span>{SUSPICIOUS_GAP_CAUTION}</span>
                    </p>
                  ) : (
                    <p className="labs-contract-note">
                      Product #{inversion.competitor.productId} has recorded final rank
                      {" "}#{inversion.competitor.finalRank}. That final position alone
                      does not establish that the earlier fusion arithmetic was correct.
                    </p>
                  )}
              </>
            )}

            <p className="labs-teaching-line">{FUSION_DEFECT_TEACHING_LINE}</p>
          </>
        )}
      </PlaygroundDisclosure>
    </div>
  );
}
