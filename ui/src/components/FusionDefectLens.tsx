import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { ApiError, api } from "../api";
import {
  BROKEN_SCORE_TIE_HEADLINE,
  candidatesFromPersistedPool,
  candidatesFromResults,
  findBrokenScoreTie,
  findFusionDefectCase,
  FUSION_DEFECT_TEACHING_LINE,
  fusedToFinalGap,
  NO_COMPETITOR_EXAMPLE,
  NO_TIE_EXAMPLE,
  SUSPICIOUS_GAP_CAUTION,
  type FusionDefectCandidate,
  type FusionDefectTie,
} from "../fusionDefect";
import { armLabel, armLanguage, FINAL_LABEL, FUSED_LABEL } from "../retrievalLanguage";
import type { RetrievalRunResponse, SearchResponse } from "../types";
import { PlaygroundDisclosure } from "./PlaygroundStage";

/**
 * Lab 2, made visible: the same measured rank produces two different numbers,
 * and every arm's own rank stops mattering once the formula is broken.
 *
 * Everything here is arithmetic on `source_rank`, never a second retrieval:
 * `armContribution` in `../fusionDefect` computes `expected` and `broken`
 * from the rank this run actually reported, so the two numbers are directly
 * comparable rather than one being asserted in prose. The headline needs no
 * search: any two single-arm candidates tie on `broken` regardless of their
 * measured ranks, so `findBrokenScoreTie` can name a pair as soon as the pool
 * holds two. A genuine fusion-order inversion is a weaker, situational claim
 * -- `findFusionDefectCase` only reports one when correct RRF, not just the
 * broken formula, would also have inverted the pair -- and needs the full
 * fused pool, not just the returned rows, so both are read lazily from the
 * persisted `search_result_event` rows on first open, the same way
 * `PersistedRunDisclosures` reads the rest of the receipt.
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

/**
 * The headline, shown wherever it is found: two single-arm candidates at the
 * two most different ranks this pool actually measured, tied on `broken` and
 * separated on `expected`. `scope` names the population the tied count is
 * drawn from -- a run's returned rows or its full fused pool -- so the count
 * is never presented without saying what it is a count of.
 */
function BrokenScoreTie({ tie, scope }: { tie: FusionDefectTie; scope: string }) {
  return (
    <>
      <p className="labs-contract-note">
        Product #{tie.lower.candidate.productId} is found only by{" "}
        {armLabel[tie.lower.arm]}, at rank #{tie.lower.sourceRank}. Product #
        {tie.higher.candidate.productId} is found only by {armLabel[tie.higher.arm]}, at
        rank #{tie.higher.sourceRank}. Correct RRF separates them --{" "}
        {tie.lower.expected.toFixed(6)} versus {tie.higher.expected.toFixed(6)} -- but the
        broken formula gives both exactly {tie.brokenScore.toFixed(6)}. {tie.singleArmCount}
        {" "}of the {tie.poolSize} candidates in {scope} are single-arm, so all of them
        collapse to that one broken score together.
      </p>
      <div className="labs-rrf-scroll" role="region" tabIndex={0} aria-label="Broken-score tie arithmetic">
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
            <CandidateRow candidate={tie.lower.candidate} highlight="better measured rank" />
            <CandidateRow candidate={tie.higher.candidate} highlight="worse measured rank" />
          </tbody>
        </table>
      </div>
    </>
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
  const poolTie = poolRows ? findBrokenScoreTie(poolRows) : null;
  const inversion = poolRows ? findFusionDefectCase(poolRows) : null;

  return (
    <>
      <p className="labs-rrf-formula">
        <code>expected = 1 / (rrf_k + source_rank)</code>. Lab 2 replaces that with{" "}
        <code>broken = 1 / (rrf_k + 1)</code> -- every arm treated as though it held
        rank 1. <code>rrf_k = {rrfK}</code> and this run's fused pool is bounded at{" "}
        <code>fused_limit = {fusedLimit}</code>, both read from this run's own
        retrieval profile, not retyped here.
      </p>

      <p className="labs-teaching-line">{BROKEN_SCORE_TIE_HEADLINE}</p>

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
        label="Check this run's full fused pool for the fusion defect"
        hint="reads this run's persisted search_result_event rows"
        onOpen={loadEvent}
      >
        {eventError ? null : poolRows === null ? (
          <p role="status">Reading mosaic.search_result_event.</p>
        ) : (
          <>
            {poolTie ? (
              <BrokenScoreTie tie={poolTie} scope="this run's full fused pool" />
            ) : (
              <p className="labs-contract-note">{NO_TIE_EXAMPLE}</p>
            )}

            {inversion === null ? (
              <p className="labs-contract-note">{NO_COMPETITOR_EXAMPLE}</p>
            ) : (
              <>
                <p className="labs-contract-note">
                  Product #{inversion.competitor.productId} sits at fused rank #
                  {inversion.competitor.fusedRank}, ahead of product #{inversion.target.productId}
                  {" "}at fused rank #{inversion.target.fusedRank} -- and unlike the tie above,
                  this is a genuine inversion: product #{inversion.target.productId} is rank #1
                  in {armLabel[inversion.targetArm]}, product #{inversion.competitor.productId}
                  &apos;s worst individual arm rank is only #{inversion.competitorWorstRank} in
                  {" "}{armLabel[inversion.competitorArm]}, and even correct RRF -- summing
                  product #{inversion.competitor.productId}&apos;s real contributions across
                  every arm it holds -- still places it ahead. The broken formula did not
                  invent this order; it just also produced it, for the wrong reason.
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
                      This run&apos;s reranker still placed product #{inversion.competitor.productId}
                      {" "}at final rank #{inversion.competitor.finalRank}. That is a reasonable
                      outcome, and it happened despite the fused order&apos;s bias toward
                      arm count, not because that bias was correct.
                    </p>
                  )}
              </>
            )}

            <p className="labs-teaching-line">{FUSION_DEFECT_TEACHING_LINE}</p>
          </>
        )}
      </PlaygroundDisclosure>
    </>
  );
}
