import { armLanguage, armPoolKey, type RetrievalArm } from "./retrievalLanguage";
import type { RetrievalRunResponse, SearchResultEventRecord } from "./types";

/**
 * The arithmetic behind the Playground's "Repair evidence" panel: two persisted
 * `mosaic.search_event` rows, diffed client-side.
 *
 * The measured Lab 1 pair is why this module exists in this shape rather than a
 * simpler one. Before and after the repair, product 2 ranks #1 in both the fused
 * pool and the final position — the only thing that moves is
 * `candidate_counts.trigram_in_pool`, 0 to 1, and the target's own `trigram_rank`,
 * absent to #1. A surface that only compared `fused_rank` and `final_rank` would
 * report "no change" on a repair that measurably worked, which is why arm
 * participation is computed and rendered as primary evidence rather than as a
 * footnote to the rank comparison.
 *
 * The second shape this guards against: event `675825de-080d-4729-89ff-f2f4ff71e555`
 * moved product 211896 from `fused_rank` 49 to `result_rank` 1 in one run, with no
 * "before" needed to see it. That is the pattern Lab 2 teaches a participant to
 * distrust — the reranker, not retrieval, produced the position — so a large
 * fused-to-final gap is flagged as a caution on the `after` run alone, never
 * praised as evidence a repair worked.
 */

/** A rank read back from `mosaic.search_result_event`. */
export type TargetRank = number | "absent";

type RankField =
  | "fused_rank"
  | "result_rank"
  | "fts_rank"
  | "trigram_rank"
  | "semantic_rank";

const armRankField: Record<RetrievalArm, RankField> = {
  fts: "fts_rank",
  trigram: "trigram_rank",
  semantic: "semantic_rank",
};

/**
 * How many rank positions a fused-pool rank can improve by reranking before the
 * move itself, rather than the arms that fed it, becomes the thing worth
 * questioning.
 *
 * Chosen relative to the default fused pool depth (`fused_limit` = 50, per
 * `db/config/retrieval.yaml`): a candidate the reranker pulls up by 10 or
 * more positions came from the bottom fifth or deeper of a typical pool, which is
 * a large enough reordering that Lab 2's lesson — a reranker move is not on its
 * own evidence retrieval found the right thing — applies. A 1-2 position swap near
 * the top is ordinary reranking noise, not a caution.
 */
export const SUSPICIOUS_GAP_THRESHOLD = 10;

export const RANK_UNCHANGED_REASSURANCE =
  "Rank held steady before and after. That is not a failed repair: this scenario "
  + "proves itself by changing which arm actually supports the result, not by "
  + "reordering an answer that was already on top.";

export const SUSPICIOUS_GAP_CAUTION =
  "Caution: this result moved a long way after reranking, from deep in the fused "
  + "pool to the top. That is exactly the pattern Lab 2 teaches you to distrust — "
  + "a big reranker move is not, on its own, evidence that a repair worked.";

export const NO_BEFORE_EVENT =
  "No earlier run to compare. If you already applied the fix, there is no way to "
  + "reconstruct a broken baseline after the fact — reset the lab, run once while "
  + "it is still broken, save that run's search_event_id, then reapply the fix and "
  + "run again. If you have not fixed anything yet, this after run can become your "
  + "before once you do.";

export interface RepairArmDelta {
  arm: RetrievalArm;
  label: string;
  mechanism: string;
  /** `null` means no before event was supplied, not a measured zero. */
  beforeInPool: number | null;
  afterInPool: number;
  /** `null` means no before event; `"absent"` means the arm found nothing there. */
  beforeTargetRank: TargetRank | null;
  afterTargetRank: TargetRank;
}

export interface RepairRankSpace {
  before: TargetRank | null;
  after: TargetRank;
}

export interface RepairGap {
  fusedRank: TargetRank;
  finalRank: TargetRank;
  /** Positions gained between the fused pool and the final position. `null` when
   * either rank is not a number (the target was absent from that space). */
  gap: number | null;
  suspicious: boolean;
}

export interface RepairEvidence {
  /** The after run's top served result. `null` if it returned no ranked rows. */
  targetProductId: number | null;
  hasBefore: boolean;
  armDeltas: RepairArmDelta[];
  fused: RepairRankSpace;
  final: RepairRankSpace;
  /** True only when a before run exists and both rank spaces are identical. */
  rankUnchanged: boolean;
  afterGap: RepairGap;
}

function candidateIn(
  run: RetrievalRunResponse,
  productId: number,
): SearchResultEventRecord | null {
  return run.candidates.find((candidate) => candidate.product_id === productId) ?? null;
}

/** The target's rank in one run. Never null: `run` here is always the after run,
 * or a before run already known to exist. */
function rankInRun(
  run: RetrievalRunResponse,
  productId: number,
  field: RankField,
): TargetRank {
  const candidate = candidateIn(run, productId);
  if (!candidate) return "absent";
  const value = candidate[field];
  return value === null || value === undefined ? "absent" : value;
}

function targetProductId(after: RetrievalRunResponse): number | null {
  return after.candidates.find((candidate) => candidate.result_rank === 1)?.product_id ?? null;
}

function computeGap(fusedRank: TargetRank, finalRank: TargetRank): RepairGap {
  const gap = typeof fusedRank === "number" && typeof finalRank === "number"
    ? fusedRank - finalRank
    : null;
  return {
    fusedRank,
    finalRank,
    gap,
    suspicious: gap !== null && gap >= SUSPICIOUS_GAP_THRESHOLD,
  };
}

/**
 * Diff two persisted retrieval events for the after run's own top result.
 *
 * The target product is always read from `after`, never supplied separately:
 * this module has no access to a scenario's `expected_techniques` or any other
 * fingerprinted evaluation input, and the after run's served #1 is the one fact
 * both worked examples in this feature's spec agree on independently of that
 * data. `before` may be `null` — a participant with no earlier run gets an
 * honest missing-before state, never a fabricated 0.
 */
export function buildRepairEvidence(
  before: RetrievalRunResponse | null,
  after: RetrievalRunResponse,
): RepairEvidence {
  const productId = targetProductId(after);

  const armDeltas: RepairArmDelta[] = armLanguage.map((arm) => {
    const field = armRankField[arm.key];
    return {
      arm: arm.key,
      label: arm.label,
      mechanism: arm.mechanism,
      beforeInPool: before ? before.run.candidate_counts[armPoolKey[arm.key]] ?? 0 : null,
      afterInPool: after.run.candidate_counts[armPoolKey[arm.key]] ?? 0,
      beforeTargetRank: before && productId !== null
        ? rankInRun(before, productId, field)
        : null,
      afterTargetRank: productId !== null ? rankInRun(after, productId, field) : "absent",
    };
  });

  const fusedBefore = before && productId !== null
    ? rankInRun(before, productId, "fused_rank")
    : null;
  const fusedAfter: TargetRank = productId !== null
    ? rankInRun(after, productId, "fused_rank")
    : "absent";
  const finalBefore = before && productId !== null
    ? rankInRun(before, productId, "result_rank")
    : null;
  const finalAfter: TargetRank = productId !== null
    ? rankInRun(after, productId, "result_rank")
    : "absent";

  return {
    targetProductId: productId,
    hasBefore: before !== null,
    armDeltas,
    fused: { before: fusedBefore, after: fusedAfter },
    final: { before: finalBefore, after: finalAfter },
    rankUnchanged: before !== null
      && productId !== null
      && fusedBefore === fusedAfter
      && finalBefore === finalAfter,
    afterGap: computeGap(fusedAfter, finalAfter),
  };
}

const SEARCH_EVENT_ID_SHAPE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a pasted string has the shape of a `search_event_id`.
 *
 * A UUID shape, not a v4-specific one: the service issues v4 ids, but this check
 * exists to reject obvious typos and prose before spending a request, not to
 * re-validate what the database will validate anyway.
 */
export function isPlausibleSearchEventId(value: string): boolean {
  return SEARCH_EVENT_ID_SHAPE.test(value.trim());
}

export function rankText(value: TargetRank | null): string {
  if (value === null) return "no earlier run";
  if (value === "absent") return "not in pool";
  return `#${value}`;
}

export function poolCountText(value: number | null): string {
  return value === null ? "no earlier run" : String(value);
}
