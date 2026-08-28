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
 * The property that is always true, and needs no search to find: because
 * `broken` is a constant per arm regardless of that arm's own rank, any two
 * candidates found by the same number of arms score identically under the
 * broken formula, however differently they ranked. Measured pools run mostly
 * single-arm, so the broken formula collapses most of the pool to one shared
 * score -- and that tie is not left undefined. `mosaic_search.search_hybrid_rrf`
 * (`db/sql/09_search_functions.sql:515`) ends `ORDER BY e.rrf_score DESC,
 * e.product_id`, so the broken formula resolves every tie by ascending
 * `product_id`, not by relevance. `brokenOrder` reproduces that exact order
 * client-side from the same measured arm ranks, and `findTieCollapseExample`
 * names a pair inside the largest tie group where the smaller `product_id`
 * belongs to the candidate with the worse real measured rank -- the broken
 * formula's own tiebreak putting the wrong one on top. This needs no search
 * over pairs across the whole pool the way a fusion-order inversion does: the
 * tie group and its product-id order fall directly out of the arm counts.
 *
 * A weaker, situational case also exists: a candidate present in several arms
 * can be inflated enough, arm by arm, to sit above a genuine single-arm rank-1
 * target in the *fused* order. That is only the defect's fault if correct RRF
 * would not also have put the competitor ahead -- two arms legitimately
 * outscoring one arm is normal RRF behavior, not a bug. `findFusionDefectCase`
 * gates on exactly that: it also sums the competitor's real `expected`
 * contributions and requires that sum to fall *below* the target's, so a pair
 * where both formulas already agree is never reported as the defect. It is
 * the secondary case here, and may correctly find nothing in a given pool --
 * the tie collapse above is the one guaranteed by the arithmetic.
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
 * window. Both `findTieCollapseExample` and `findFusionDefectCase` need this
 * reach: the tie collapse is `mosaic_search.search_hybrid_rrf`'s own `ORDER
 * BY`, over the pool it actually ran on, and a genuine inversion is routinely
 * outside the returned rows.
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

/** Arms an arm-set actually found the candidate in, `expected`/`broken` both non-null. */
function presentArms(candidate: FusionDefectCandidate): FusionDefectArm[] {
  return candidate.arms.filter((arm) => arm.sourceRank !== null);
}

/** The correct-RRF sum across a candidate's present arms -- never the broken one. */
function expectedSum(arms: FusionDefectArm[]): number {
  return arms.reduce((sum, arm) => sum + arm.expected!, 0);
}

export interface FusionDefectBrokenRank {
  candidate: FusionDefectCandidate;
  /** Sum of `broken` across present arms -- depends only on arm count. */
  brokenScore: number;
  /** Sum of `expected` across present arms -- the correct RRF score. */
  correctScore: number;
  armCount: number;
  /** 1-based position under `ORDER BY brokenScore DESC, product_id ASC`. */
  brokenRank: number;
}

/**
 * The broken formula's own order, computed the way the SQL computes it.
 *
 * `mosaic_search.search_hybrid_rrf` (`db/sql/09_search_functions.sql:515`)
 * ends `ORDER BY e.rrf_score DESC, e.product_id`. Swap in the broken
 * per-arm constant for `e.rrf_score` and that `ORDER BY` is exactly this
 * sort: broken score descending, ties broken by ascending `product_id`.
 * Nothing here invents a tiebreak -- it is the one line 515 already runs.
 */
export function brokenOrder(candidates: FusionDefectCandidate[]): FusionDefectBrokenRank[] {
  const scored = candidates.map((candidate) => {
    const present = presentArms(candidate);
    return {
      candidate,
      brokenScore: present.reduce((sum, arm) => sum + arm.broken!, 0),
      correctScore: expectedSum(present),
      armCount: present.length,
    };
  });
  return [...scored]
    .sort((a, b) => (b.brokenScore !== a.brokenScore
      ? b.brokenScore - a.brokenScore
      : a.candidate.productId - b.candidate.productId))
    .map((entry, index) => ({ ...entry, brokenRank: index + 1 }));
}

/**
 * How many pairs the broken order and the real measured order disagree on.
 *
 * `ranked` is already in broken order (index order === `brokenRank` order),
 * so for every `i < j`, the broken formula placed `ranked[i]` ahead of
 * `ranked[j]`. That pair is discordant -- inverted relative to reality --
 * exactly when the real measured order (`fusedRank`) says the opposite:
 * `ranked[i]` actually ranked worse than `ranked[j]`.
 */
export function invertedPairCount(ranked: FusionDefectBrokenRank[]): number {
  let count = 0;
  for (let i = 0; i < ranked.length; i++) {
    for (let j = i + 1; j < ranked.length; j++) {
      if (ranked[i].candidate.fusedRank > ranked[j].candidate.fusedRank) count++;
    }
  }
  return count;
}

export interface FusionDefectTieCollapse {
  /** The full broken order, for a caller that wants more than the headline pair. */
  ranked: FusionDefectBrokenRank[];
  /** How many distinct broken scores exist -- one per distinct arm count present. */
  distinctBrokenScores: number;
  /** Size of the largest group of candidates tied on one broken score. */
  tieGroupSize: number;
  poolSize: number;
  /** Count of pairs where the broken order and the real measured order disagree. */
  invertedPairs: number;
  /** Smaller `product_id`, ranked ahead under the broken formula despite the worse real rank. */
  first: FusionDefectBrokenRank;
  /** Larger `product_id`, ranked behind `first` despite the better real rank. */
  second: FusionDefectBrokenRank;
}

/**
 * The defect in its purest, most persuasive form: two real candidates, tied
 * on the broken score because they share an arm count, where the broken
 * formula's own `product_id` tiebreak puts the genuinely worse one on top.
 *
 * No cross-arm-count search, and no dependence on any one target holding
 * rank 1 -- the largest tie group in this pool is the widest place the
 * broken formula collapses relevance to a single number, so it is where the
 * tiebreak does the most damage. Within that group, the pair kept is the one
 * with the largest real-rank spread where the smaller `product_id` is truly
 * the worse candidate: the pair a skeptic has the least room to dismiss as
 * an artifact of near-identical relevance. Returns `null` only when no two
 * pool members share an arm count, or when ascending `product_id` inside the
 * largest tie group happens to already agree with the real order -- both
 * true facts about that pool, not a gap in this function.
 */
export function findTieCollapseExample(
  candidates: FusionDefectCandidate[],
): FusionDefectTieCollapse | null {
  const ranked = brokenOrder(candidates);

  const groups = new Map<number, FusionDefectBrokenRank[]>();
  for (const entry of ranked) {
    const list = groups.get(entry.brokenScore) ?? [];
    list.push(entry);
    groups.set(entry.brokenScore, list);
  }

  let largest: FusionDefectBrokenRank[] | null = null;
  for (const group of groups.values()) {
    if (largest === null || group.length > largest.length) largest = group;
  }
  if (largest === null || largest.length < 2) return null;

  let best: { first: FusionDefectBrokenRank; second: FusionDefectBrokenRank; spread: number } | null =
    null;
  for (const x of largest) {
    for (const y of largest) {
      if (x.candidate.productId >= y.candidate.productId) continue;
      if (x.candidate.fusedRank <= y.candidate.fusedRank) continue;
      const spread = x.candidate.fusedRank - y.candidate.fusedRank;
      if (best === null || spread > best.spread) best = { first: x, second: y, spread };
    }
  }
  if (best === null) return null;

  return {
    ranked,
    distinctBrokenScores: groups.size,
    tieGroupSize: largest.length,
    poolSize: candidates.length,
    invertedPairs: invertedPairCount(ranked),
    first: best.first,
    second: best.second,
  };
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
 * A genuine fusion-order inversion: a rank-1, single-arm target that a
 * multi-arm competitor already sits above in the reported fused order, where
 * correct RRF -- not just the broken formula -- would also have put the
 * competitor ahead.
 *
 * That last clause is load-bearing. A multi-arm competitor sitting above a
 * single-arm rank-1 target in the fused order is not, on its own, evidence of
 * the defect: two real arms are allowed to legitimately outscore one. This
 * only qualifies as the defect's fault when the competitor's *own* summed
 * `expected` contributions -- the correct formula, computed from its real
 * measured ranks -- fall below the target's single `expected` contribution.
 * Skipping that check is exactly the bug that shipped one real pair as "the
 * defect" when both formulas agreed on its order.
 *
 * Reads `fusedRank` as reported, never a recomputed hypothetical: this is
 * what this run actually did, not a projection. Among every qualifying pair,
 * keeps the one with the worst competitor rank, because that is the pair a
 * skeptic has the least room to dismiss as noise. Returns `null` when the
 * pool holds no such pair, which is a true fact about that pool, not a gap in
 * this function.
 */
export function findFusionDefectCase(
  candidates: FusionDefectCandidate[],
): FusionDefectExample | null {
  const targets = candidates
    .map((candidate) => {
      const present = presentArms(candidate);
      if (present.length !== 1 || present[0].sourceRank !== 1) return null;
      return { candidate, arm: present[0].arm, expected: present[0].expected! };
    })
    .filter(
      (value): value is { candidate: FusionDefectCandidate; arm: RetrievalArm; expected: number } =>
        value !== null,
    );

  let best: FusionDefectExample | null = null;
  for (const { candidate: target, arm: targetArm, expected: targetExpected } of targets) {
    for (const competitor of candidates) {
      if (competitor.productId === target.productId) continue;
      if (competitor.fusedRank >= target.fusedRank) continue;
      const present = presentArms(competitor);
      if (present.length <= 1) continue;
      // Correct RRF must also invert the pair -- otherwise both formulas
      // agree and this is not the defect, just two arms beating one.
      if (expectedSum(present) >= targetExpected) continue;
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

export const BROKEN_TIE_MECHANISM =
  "Every arm contributes exactly 1 / (rrf_k + 1) under the broken formula, "
  + "no matter its own rank -- so candidates with equal arm counts tie "
  + "exactly. mosaic_search.search_hybrid_rrf breaks that tie on ascending "
  + "product_id, not relevance. The broken formula does not fail to rank "
  + "these candidates; it ranks them by product id.";

export const NO_TIE_COLLAPSE_EXAMPLE =
  "This run's full fused pool holds no two candidates sharing an arm count "
  + "with the smaller product_id belonging to the truly worse one -- either "
  + "no two candidates share an arm count at all, or the largest tie group's "
  + "product_id order happens to already agree with the real measured "
  + "order. Try another query if this pool happens not to have the shape.";

export const NO_COMPETITOR_EXAMPLE =
  "This run's fused pool holds no rank-1 single-arm target that a multi-arm "
  + "competitor already outranks under both formulas. That pairing needs a "
  + "candidate found by only one arm at that arm's own rank 1, a different "
  + "candidate found by more than one arm ranked ahead of it in the fused "
  + "order, and that competitor's own correct RRF contributions -- summed "
  + "across every arm it holds -- adding up to less than the target's single "
  + "contribution. Two arms legitimately outscoring one arm is not the "
  + "defect; try another query if this pool happens not to have a pair that "
  + "clears that bar.";

export const FUSION_DEFECT_TEACHING_LINE =
  "A correct answer is not proof of a correct pipeline.";
