import { armLanguage, type RetrievalArm } from "./retrievalLanguage";
import { SUSPICIOUS_GAP_CAUTION, SUSPICIOUS_GAP_THRESHOLD } from "./repairEvidence";
import type { ProductSummary, SearchResultEventRecord } from "./types";

/**
 * Lab 2's defect, as arithmetic rather than as a story.
 *
 * `mosaic_search.reciprocal_rank_contribution` (`scripts/lab_state.py`,
 * `LAB2_BROKEN_FORMULA`) replaces `1 / (rrf_k + source_rank)` with
 * `1 / (rrf_k + 1)`. Arithmetically that treats every arm's own rank as 1:
 *
 *   - a genuine rank-1 result is unaffected. `1 / (rrf_k + 1)` is exactly what
 *     the correct formula already produces at rank 1, so `expected` and
 *     `broken` are the same number.
 *   - every other rank is inflated up to that same ceiling. `broken` is never
 *     smaller than `expected`, and the gap grows with how far the true rank
 *     was from 1.
 *
 * A candidate present in several arms is inflated once per arm it appears in,
 * independent of how well it ranked in any of them, which is why a pool built
 * mostly of single-arm candidates lets a mediocre multi-arm one sit above a
 * genuine single-arm rank-1 target. `findCompetitorAboveTarget` names one.
 *
 * `armContribution` computes both formulas from the same measured
 * `source_rank`, so a caller shows the two numbers side by side rather than
 * asserting the difference in prose. Everything else here reads real ranks
 * out of a `SearchResponse` or a persisted `search_result_event` row --
 * never a fixture, and never a recomputed "if it were broken" fused score
 * presented as though it happened.
 */

export interface FusionDefectArm {
  arm: RetrievalArm;
  label: string;
  /** `null` means that arm never found this candidate. */
  sourceRank: number | null;
  /** `1 / (rrf_k + sourceRank)`. `null` when the arm never found it. */
  expected: number | null;
  /** `1 / (rrf_k + 1)`. `null` when the arm never found it. */
  broken: number | null;
}

export interface FusionDefectCandidate {
  productId: number;
  title: string;
  /** Position in the fused pool, before reranking. Primary rank space. */
  fusedRank: number;
  /** Position among the returned, reranked rows. */
  finalRank: number;
  arms: FusionDefectArm[];
}

/**
 * The two formulas, from one measured rank.
 *
 * Equal at `sourceRank === 1` by construction: that is the arithmetic fact the
 * defect turns on, not a coincidence of this implementation.
 */
export function armContribution(
  sourceRank: number | null,
  rrfK: number,
): { expected: number | null; broken: number | null } {
  if (sourceRank === null) return { expected: null, broken: null };
  return {
    expected: 1 / (rrfK + sourceRank),
    broken: 1 / (rrfK + 1),
  };
}

function buildArms(
  ranks: Record<RetrievalArm, number | null>,
  rrfK: number,
): FusionDefectArm[] {
  return armLanguage.map((arm) => {
    const sourceRank = ranks[arm.key];
    const { expected, broken } = armContribution(sourceRank, rrfK);
    return { arm: arm.key, label: arm.label, sourceRank, expected, broken };
  });
}

/**
 * One row per returned result, read straight off `response.results` -- the
 * same signals `RrfMath` and `CandidateRows` already render, so this never
 * asks the service for anything the page has not already fetched.
 */
export function candidatesFromResults(
  products: ProductSummary[],
  rrfK: number,
): FusionDefectCandidate[] {
  return products
    .filter((product) => product.signals !== null)
    .map((product) => {
      const signals = product.signals!;
      return {
        productId: product.product_id,
        title: product.model,
        fusedRank: signals.pre_rerank_rank,
        finalRank: signals.final_rank,
        arms: buildArms(
          {
            fts: signals.fts.rank,
            trigram: signals.trigram.rank,
            semantic: signals.semantic.rank,
          },
          rrfK,
        ),
      };
    });
}

/**
 * One row per pool member, read from the persisted `search_result_event`
 * rows -- the full fused pool, up to `fused_limit`, not just the returned
 * window. `findCompetitorAboveTarget` needs this reach: the measured example
 * it exists to find is routinely outside the returned rows.
 */
export function candidatesFromPersistedPool(
  candidates: SearchResultEventRecord[],
  rrfK: number,
): FusionDefectCandidate[] {
  return candidates
    .filter((candidate) => candidate.fused_rank !== null)
    .map((candidate) => ({
      productId: candidate.product_id,
      title: `product ${candidate.product_id}`,
      fusedRank: candidate.fused_rank as number,
      finalRank: candidate.result_rank,
      arms: buildArms(
        {
          fts: candidate.fts_rank,
          trigram: candidate.trigram_rank,
          semantic: candidate.semantic_rank,
        },
        rrfK,
      ),
    }));
}

export interface FusionDefectExample {
  target: FusionDefectCandidate;
  targetArm: RetrievalArm;
  competitor: FusionDefectCandidate;
  competitorArm: RetrievalArm;
  /** The competitor's own worst arm rank -- the number that makes the case. */
  competitorWorstRank: number;
}

/**
 * The most persuasive real instance in one pool: a rank-1, single-arm target
 * that a multi-arm competitor -- with a materially worse rank in every arm it
 * holds -- already sits above in the reported fused order.
 *
 * Reads `fusedRank` as reported, never a recomputed hypothetical: this is
 * what this run actually did, not a projection. Among every qualifying pair,
 * keeps the one with the worst competitor rank, because that is the pair a
 * skeptic has the least room to dismiss as noise. Returns `null` when the
 * pool holds no such pair, which is a true fact about that pool, not a gap in
 * this function.
 */
export function findCompetitorAboveTarget(
  candidates: FusionDefectCandidate[],
): FusionDefectExample | null {
  const targets = candidates
    .map((candidate) => {
      const present = candidate.arms.filter((arm) => arm.sourceRank !== null);
      if (present.length !== 1 || present[0].sourceRank !== 1) return null;
      return { candidate, arm: present[0].arm };
    })
    .filter((value): value is { candidate: FusionDefectCandidate; arm: RetrievalArm } =>
      value !== null);

  let best: FusionDefectExample | null = null;
  for (const { candidate: target, arm: targetArm } of targets) {
    for (const competitor of candidates) {
      if (competitor.productId === target.productId) continue;
      if (competitor.fusedRank >= target.fusedRank) continue;
      const present = competitor.arms.filter((arm) => arm.sourceRank !== null);
      if (present.length <= 1) continue;
      const worst = present.reduce(
        (worstArm, arm) => (arm.sourceRank! > worstArm.sourceRank! ? arm : worstArm),
      );
      if (worst.sourceRank! <= 1) continue;
      if (best === null || worst.sourceRank! > best.competitorWorstRank) {
        best = {
          target,
          targetArm,
          competitor,
          competitorArm: worst.arm,
          competitorWorstRank: worst.sourceRank!,
        };
      }
    }
  }
  return best;
}

export interface FusionDefectGap {
  gap: number;
  suspicious: boolean;
}

/**
 * The fused-to-final movement, in the same units and against the same
 * threshold `RepairEvidence.tsx` already established. A big gap reads as
 * suspicious there and reads as suspicious here, on purpose: two surfaces
 * disagreeing about what counts as a large reranker move would teach a
 * participant that the threshold is a style choice rather than a measured
 * line.
 */
export function fusedToFinalGap(candidate: FusionDefectCandidate): FusionDefectGap {
  const gap = candidate.fusedRank - candidate.finalRank;
  return { gap, suspicious: gap >= SUSPICIOUS_GAP_THRESHOLD };
}

export { SUSPICIOUS_GAP_CAUTION };

export const NO_COMPETITOR_EXAMPLE =
  "This run's fused pool holds no rank-1 single-arm target that a multi-arm "
  + "competitor already outranks. That pairing needs both a candidate found "
  + "by only one arm, at that arm's own rank 1, and a different candidate "
  + "found by more than one arm ranked ahead of it -- try another query if "
  + "this pool happens not to have one.";

export const FUSION_DEFECT_TEACHING_LINE =
  "A correct answer is not proof of a correct pipeline.";
