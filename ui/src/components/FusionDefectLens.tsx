import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { ApiError, api } from "../api";
import {
  candidatesFromPersistedPool,
  candidatesFromResults,
  findCompetitorAboveTarget,
  FUSION_DEFECT_TEACHING_LINE,
  fusedToFinalGap,
  NO_COMPETITOR_EXAMPLE,
  SUSPICIOUS_GAP_CAUTION,
  type FusionDefectCandidate,
} from "../fusionDefect";
import { armLabel, armLanguage, FINAL_LABEL, FUSED_LABEL } from "../retrievalLanguage";
import type { RetrievalRunResponse, SearchResponse } from "../types";
import { PlaygroundDisclosure } from "./PlaygroundStage";

/**
 * Lab 2, made visible: the same measured rank produces two different numbers,
 * and one candidate a competitor can already sit above in the fused order.
 *
 * Everything here is arithmetic on `source_rank`, never a second retrieval:
 * `armContribution` in `../fusionDefect` computes `expected` and `broken`
 * from the rank this run actually reported, so the two numbers are directly
 * comparable rather than one being asserted in prose. The persuasive part --
 * a materially worse-ranked competitor already outranking a genuine rank-1
 * target -- needs the full fused pool, not just the returned rows, so it is
 * read lazily from the persisted `search_result_event` rows on first open,
 * the same way `PersistedRunDisclosures` reads the rest of the receipt.
 */

function armCells(candidate: FusionDefectCandidate) {
  return candidate.arms.map((arm) => (
    <td className="mono" key={arm.arm}>
      {arm.sourceRank === null ? (
        <em>not found</em>
      ) : (
        <>
          <span>rank #{arm.sourceRank}</span>
          <b>{arm.expected?.toFixed(6)}</b>
          <em className={arm.sourceRank === 1 ? "" : "labs-rrf-mismatch"}>
            broken {arm.broken?.toFixed(6)}
          </em>
        </>
      )}
    </td>
  ));
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

export function FusionDefectLens({ response }: { response: SearchResponse }) {
  const [event, setEvent] = useState<RetrievalRunResponse | null>(null);
  const [eventError, setEventError] = useState("");

  function loadEvent() {
    if (event || eventError) return;
    api
      .retrievalEvent(response.search_event_id)
      .then(setEvent)
      .catch((cause: unknown) => {
        setEventError(
          cause instanceof ApiError && cause.status === 404
            ? "This run's persisted pool was not found."
            : cause instanceof Error
              ? cause.message
              : "This run's persisted pool could not be read",
        );
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
  const example = poolRows ? findCompetitorAboveTarget(poolRows) : null;

  return (
    <>
      <p className="labs-rrf-formula">
        <code>expected = 1 / (rrf_k + source_rank)</code>. Lab 2 replaces that with{" "}
        <code>broken = 1 / (rrf_k + 1)</code> -- every arm treated as though it held
        rank 1. <code>rrf_k = {rrfK}</code> and this run's fused pool is bounded at{" "}
        <code>fused_limit = {fusedLimit}</code>, both read from this run's own
        retrieval profile, not retyped here.
      </p>

      <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Fusion defect arithmetic">
        <table className="labs-rrf-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              {armLanguage.map((arm) => (
                <th key={arm.key} scope="col">{arm.label}</th>
              ))}
              <th scope="col">{FUSED_LABEL}</th>
              <th scope="col">{FINAL_LABEL}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((candidate) => (
              <CandidateRow candidate={candidate} key={candidate.productId} />
            ))}
          </tbody>
        </table>
      </div>

      {eventError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          <span>{eventError}</span>
        </p>
      ) : null}

      <PlaygroundDisclosure
        label="Check the full fused pool for a competitor above a rank-1 target"
        hint="reads this run's persisted search_result_event rows"
        onOpen={loadEvent}
      >
        {eventError ? null : poolRows === null ? (
          <p role="status">Reading mosaic.search_result_event.</p>
        ) : example === null ? (
          <p className="labs-contract-note">{NO_COMPETITOR_EXAMPLE}</p>
        ) : (
          <>
            <p className="labs-contract-note">
              Product #{example.competitor.productId} sits at fused rank #
              {example.competitor.fusedRank}, ahead of product #{example.target.productId}
              {" "}at fused rank #{example.target.fusedRank} -- even though product #
              {example.target.productId} is rank #1 in {armLabel[example.targetArm]}, and
              product #{example.competitor.productId}&apos;s worst individual arm rank is
              only #{example.competitorWorstRank}, in {armLabel[example.competitorArm]}.
              Under the broken formula both of those facts stop mattering: every arm
              present contributes the same constant regardless of its own rank, so the
              multi-arm candidate keeps its multiple-of-the-constant lead and the
              single-arm rank-1 result cannot close the gap by ranking any better than
              it already does.
            </p>

            <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Competitor and target arithmetic">
              <table className="labs-rrf-table">
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    {armLanguage.map((arm) => (
                      <th key={arm.key} scope="col">{arm.label}</th>
                    ))}
                    <th scope="col">{FUSED_LABEL}</th>
                    <th scope="col">{FINAL_LABEL}</th>
                  </tr>
                </thead>
                <tbody>
                  <CandidateRow candidate={example.competitor} highlight="competitor" />
                  <CandidateRow candidate={example.target} highlight="rank-1 target" />
                </tbody>
              </table>
            </div>

            {fusedToFinalGap(example.competitor).suspicious
              || fusedToFinalGap(example.target).suspicious ? (
                <p className="labs-repair-caution" role="alert">
                  <AlertTriangle aria-hidden="true" size={15} />
                  <span>{SUSPICIOUS_GAP_CAUTION}</span>
                </p>
              ) : (
                <p className="labs-contract-note">
                  This run&apos;s reranker still placed product #{example.competitor.productId}
                  {" "}at final rank #{example.competitor.finalRank}. That is a reasonable
                  outcome, and it happened despite the fused order&apos;s bias toward
                  arm count, not because that bias was correct.
                </p>
              )}

            <p className="labs-teaching-line">{FUSION_DEFECT_TEACHING_LINE}</p>
          </>
        )}
      </PlaygroundDisclosure>
    </>
  );
}
