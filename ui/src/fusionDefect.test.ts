import { describe, expect, it } from "vitest";
import {
  armContribution,
  candidatesFromPersistedPool,
  candidatesFromResults,
  findBrokenScoreTie,
  findFusionDefectCase,
  fusedToFinalGap,
  type FusionDefectCandidate,
} from "./fusionDefect";
import { SUSPICIOUS_GAP_THRESHOLD } from "./repairEvidence";
import type { ProductSummary, ResultSignals, SearchResultEventRecord } from "./types";

/**
 * Measured live pool, query "noise cancelling headphones",
 * search_event_id 8cb50318-c61a-42c8-bf6c-5df9dc229983, `rrf_k` 60:
 *
 *   product 4     (Halo Comfort SE):  fts_rank 3, trigram_rank 4, fused_rank 4
 *   product 14552 (NovaLogic OH-K044): semantic_rank 1, fused_rank 8
 *   product 3992:                      semantic_rank 3, fused_rank 10
 *   product 4868:                      semantic_rank 5, fused_rank 12
 *   product 5995:                      semantic_rank 7, fused_rank 17
 *   product 46809:                     semantic_rank 4, fused_rank 11
 *
 * This pool does double duty:
 *
 *   - five of its six candidates (everything but product 4) are single-arm,
 *     at five different measured ranks. That is the always-true tie
 *     `findBrokenScoreTie` names: every one of them collapses to the same
 *     broken score, `1 / (rrf_k + 1)`, while correct RRF spreads them from
 *     1/61 down to 1/67.
 *   - product 4 (fts_rank 3, trigram_rank 4) sits at fused rank 4, above
 *     product 14552's fused rank 8, even though product 14552 is a genuine
 *     single-arm rank-1 result. That looks like the fusion defect, but it
 *     is not one: correct RRF agrees with the broken formula on this pair
 *     (0.031498 for product 4 vs. 0.016393 for product 14552 -- product 4
 *     wins under both). `findFusionDefectCase` must reject this exact shape,
 *     which is the regression a prior version of this module shipped.
 */
const POOL: SearchResultEventRecord[] = [
  {
    product_id: 4,
    result_rank: 1,
    fts_rank: 3,
    trigram_rank: 4,
    semantic_rank: null,
    fused_rank: 4,
    rerank_rank: 1,
    scores: {},
    provenance: {},
  },
  {
    product_id: 14552,
    result_rank: 18,
    fts_rank: null,
    trigram_rank: null,
    semantic_rank: 1,
    fused_rank: 8,
    rerank_rank: 18,
    scores: {},
    provenance: {},
  },
  {
    product_id: 3992,
    result_rank: 10,
    fts_rank: null,
    trigram_rank: null,
    semantic_rank: 3,
    fused_rank: 10,
    rerank_rank: 10,
    scores: {},
    provenance: {},
  },
  {
    product_id: 4868,
    result_rank: 7,
    fts_rank: null,
    trigram_rank: null,
    semantic_rank: 5,
    fused_rank: 12,
    rerank_rank: 7,
    scores: {},
    provenance: {},
  },
  {
    product_id: 5995,
    result_rank: 12,
    fts_rank: null,
    trigram_rank: null,
    semantic_rank: 7,
    fused_rank: 17,
    rerank_rank: 12,
    scores: {},
    provenance: {},
  },
  {
    product_id: 46809,
    result_rank: 49,
    fts_rank: null,
    trigram_rank: null,
    semantic_rank: 4,
    fused_rank: 11,
    rerank_rank: 49,
    scores: {},
    provenance: {},
  },
];

const RRF_K = 60;

function signals(overrides: Partial<ResultSignals>): ResultSignals {
  return {
    fts: { rank: null, raw_score: null, rrf_contribution: null },
    trigram: { rank: null, raw_score: null, rrf_contribution: null },
    semantic: { rank: null, raw_score: null, rrf_contribution: null },
    rrf_score: 0,
    pre_rerank_rank: 1,
    pre_rerank_score: 0,
    rerank_score: null,
    final_rank: 1,
    score_semantics: "rrf",
    ...overrides,
  };
}

function product(overrides: Partial<ProductSummary> & { product_id: number }): ProductSummary {
  return {
    sku: `SKU-${overrides.product_id}`,
    title: `Product ${overrides.product_id}`,
    short_description: "",
    domain: "consumer_electronics",
    category_key: "over-ear-headphones",
    category_path: "Audio > Over-Ear Headphones",
    brand: "Brand",
    model: `Model ${overrides.product_id}`,
    price_cents: 1000,
    list_price_cents: 1000,
    currency: "USD",
    rating: null,
    review_count: 0,
    availability: "in_stock",
    inventory_count: 1,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: false,
    is_retrieval_anchor: false,
    image_url: null,
    image_source: null,
    signals: null,
    sources: [],
    ...overrides,
  };
}

describe("armContribution", () => {
  it("agrees with the broken formula exactly at rank 1 -- the arithmetic the defect turns on", () => {
    const { expected, broken } = armContribution(1, RRF_K);
    expect(expected).toBe(broken);
    expect(expected).toBeCloseTo(1 / 61, 12);
  });

  it("diverges from the broken formula for any rank other than 1", () => {
    const { expected, broken } = armContribution(5, RRF_K);
    expect(expected).not.toBe(broken);
    expect(expected).toBeCloseTo(1 / 65, 12);
    expect(broken).toBeCloseTo(1 / 61, 12);
    // The broken constant is a ceiling: it never understates a contribution.
    expect(broken).toBeGreaterThan(expected!);
  });

  it("reports both formulas as absent when the arm never found the candidate", () => {
    expect(armContribution(null, RRF_K)).toEqual({ expected: null, broken: null });
  });
});

describe("candidatesFromResults / candidatesFromPersistedPool", () => {
  /**
   * The priority gate: the Lab 2 view must show expected and broken as
   * *different* values for a result whose source rank is not 1, and
   * *identical* values for one whose source rank is 1. A presence-only test
   * (just checking both fields exist) would pass on a component that always
   * printed the same number for both, which is exactly the failure mode this
   * asserts against.
   */
  it("keeps expected and broken different for a non-rank-1 arm, and identical for a rank-1 arm, on real returned rows", () => {
    const results: ProductSummary[] = [
      product({
        product_id: 4,
        model: "Comfort SE",
        signals: signals({
          fts: { rank: 3, raw_score: 1.5, rrf_contribution: 1 / 63 },
          trigram: { rank: 4, raw_score: 1, rrf_contribution: 1 / 64 },
          pre_rerank_rank: 4,
          final_rank: 1,
        }),
      }),
      product({
        product_id: 14552,
        model: "OH-K044",
        signals: signals({
          semantic: { rank: 1, raw_score: 0.44, rrf_contribution: 1 / 61 },
          pre_rerank_rank: 8,
          final_rank: 18,
        }),
      }),
    ];

    const rows = candidatesFromResults(results, RRF_K);
    const competitor = rows.find((row) => row.productId === 4)!;
    const target = rows.find((row) => row.productId === 14552)!;

    const competitorFts = competitor.arms.find((arm) => arm.arm === "fts")!;
    expect(competitorFts.sourceRank).toBe(3);
    expect(competitorFts.expected).not.toBe(competitorFts.broken);
    expect(competitorFts.expected).toBeCloseTo(1 / 63, 12);
    expect(competitorFts.broken).toBeCloseTo(1 / 61, 12);

    const targetSemantic = target.arms.find((arm) => arm.arm === "semantic")!;
    expect(targetSemantic.sourceRank).toBe(1);
    expect(targetSemantic.expected).toBe(targetSemantic.broken);
    expect(targetSemantic.expected).toBeCloseTo(1 / 61, 12);
  });

  it("builds the same shape from the persisted pool as from returned results", () => {
    const rows = candidatesFromPersistedPool(POOL, RRF_K);
    expect(rows).toHaveLength(POOL.length);
    const target = rows.find((row) => row.productId === 14552)!;
    const semantic = target.arms.find((arm) => arm.arm === "semantic")!;
    expect(semantic.sourceRank).toBe(1);
    expect(semantic.expected).toBe(semantic.broken);
  });
});

describe("findBrokenScoreTie", () => {
  /**
   * The gate this module leads with: two real single-arm candidates from the
   * measured pool, at the two most different ranks it actually holds, tie
   * exactly on the broken formula and separate cleanly under the correct one.
   * That is not a coincidence of this pool -- it is the arithmetic identity
   * `armContribution` establishes for every single-arm candidate everywhere.
   */
  it("ties the pool's most different single-arm ranks on broken score while expected separates them", () => {
    // Witness, independent of the function's own verdict: five of the six
    // pool members are single-arm, so the search has more than the winning
    // pair to consider.
    const rows = candidatesFromPersistedPool(POOL, RRF_K);
    const singleArmCount = rows.filter(
      (row) => row.arms.filter((arm) => arm.sourceRank !== null).length === 1,
    ).length;
    expect(singleArmCount).toBe(5);

    const tie = findBrokenScoreTie(rows);

    expect(tie).not.toBeNull();
    expect(tie!.lower.candidate.productId).toBe(14552);
    expect(tie!.lower.sourceRank).toBe(1);
    expect(tie!.higher.candidate.productId).toBe(5995);
    expect(tie!.higher.sourceRank).toBe(7);

    // Broken: the identical constant, regardless of how differently they ranked.
    expect(tie!.lower.broken).toBe(tie!.higher.broken);
    expect(tie!.lower.broken).toBeCloseTo(1 / 61, 12);
    expect(tie!.brokenScore).toBe(tie!.lower.broken);

    // Expected: correct RRF separates them cleanly.
    expect(tie!.lower.expected).not.toBe(tie!.higher.expected);
    expect(tie!.lower.expected).toBeGreaterThan(tie!.higher.expected);
    expect(tie!.lower.expected).toBeCloseTo(1 / 61, 12);
    expect(tie!.higher.expected).toBeCloseTo(1 / 67, 12);

    expect(tie!.singleArmCount).toBe(5);
    expect(tie!.poolSize).toBe(6);
  });

  it("returns null when fewer than two candidates are single-arm", () => {
    const onlyOneSingleArm: SearchResultEventRecord[] = [
      POOL[0], // product 4, two arms
      POOL[1], // product 14552, one arm -- the only single-arm member
    ];
    const rows = candidatesFromPersistedPool(onlyOneSingleArm, RRF_K);
    expect(findBrokenScoreTie(rows)).toBeNull();
  });

  it("returns null when every single-arm candidate shares one measured rank", () => {
    const sameRank: SearchResultEventRecord[] = POOL
      .filter((row) => row.product_id !== 4)
      .map((row) => ({ ...row, semantic_rank: 1 }));
    const rows = candidatesFromPersistedPool(sameRank, RRF_K);
    expect(findBrokenScoreTie(rows)).toBeNull();
  });
});

describe("findFusionDefectCase", () => {
  /**
   * The regression this module shipped: product 4 (two arms, ranks 3 and 4)
   * sits above product 14552 (one arm, rank 1) in the fused order, but
   * correct RRF agrees with that order -- 0.031498 for product 4 versus
   * 0.016393 for product 14552. A prior version reported this pair as "the
   * fusion defect" without ever checking that correct RRF would have ordered
   * the pair differently. It would not have. This is the exact shape that
   * regression shipped, and the function must reject it.
   */
  it("rejects the measured product-4-vs-14552 pair: correct RRF agrees with the broken order", () => {
    const rows = candidatesFromPersistedPool(POOL, RRF_K);

    // Witness the arithmetic directly, independent of the function's verdict.
    const competitor = rows.find((row) => row.productId === 4)!;
    const target = rows.find((row) => row.productId === 14552)!;
    const competitorExpectedSum = competitor.arms
      .filter((arm) => arm.sourceRank !== null)
      .reduce((sum, arm) => sum + arm.expected!, 0);
    const targetExpected = target.arms.find((arm) => arm.arm === "semantic")!.expected!;
    expect(competitorExpectedSum).toBeGreaterThan(targetExpected);

    expect(findFusionDefectCase(rows)).toBeNull();
  });

  it("is red at birth: fails once the target's rank-1 fact is corrupted to rank 2", () => {
    // The exact edit `findFusionDefectCase` exists to catch: a target that no
    // longer truly holds rank 1 in its one arm must stop qualifying.
    const corrupted = POOL.map((row) =>
      row.product_id === 14552 ? { ...row, semantic_rank: 2 } : row);
    const rows = candidatesFromPersistedPool(corrupted, RRF_K);
    expect(findFusionDefectCase(rows)).toBeNull();
  });

  it("does not fire on an unrelated pool with no multi-arm competitor", () => {
    // Independence: a pool where every candidate is single-arm has no
    // competitor to find, regardless of who holds rank 1.
    const singleArmOnly: SearchResultEventRecord[] = POOL.map((row) => ({
      ...row,
      fts_rank: null,
      trigram_rank: null,
      semantic_rank: row.product_id === 14552 ? 1 : row.semantic_rank ?? 9,
    }));
    const rows = candidatesFromPersistedPool(singleArmOnly, RRF_K);
    expect(findFusionDefectCase(rows)).toBeNull();
  });

  /**
   * A genuine inversion, constructed so correct RRF also inverts the pair --
   * the predicate `findFusionDefectCase` exists to require. `rrf_k = 60`, so
   * a single-arm rank-1 target's own contribution is `1 / 61 = 0.016393`.
   * Competitor A holds two arms at ranks 200 and 210 (sum ~= 0.007464);
   * competitor B holds two arms at ranks 300 and 305 (sum ~= 0.005518). Both
   * sums fall well under 0.016393, so correct RRF places either one above
   * the target too -- this is a real fusion-order inversion, not two arms
   * legitimately outscoring one. B's worst rank (305) is worse than A's
   * (210), so B is the one a skeptic has the least room to dismiss.
   */
  it("keeps the qualifying competitor with the worse individual rank when more than one qualifies", () => {
    const target: SearchResultEventRecord = {
      product_id: 1,
      result_rank: 5,
      fts_rank: null,
      trigram_rank: null,
      semantic_rank: 1,
      fused_rank: 3,
      rerank_rank: 5,
      scores: {},
      provenance: {},
    };
    const competitorA: SearchResultEventRecord = {
      product_id: 2,
      result_rank: 1,
      fts_rank: 200,
      trigram_rank: 210,
      semantic_rank: null,
      fused_rank: 1,
      rerank_rank: 1,
      scores: {},
      provenance: {},
    };
    const competitorB: SearchResultEventRecord = {
      product_id: 3,
      result_rank: 2,
      fts_rank: 300,
      trigram_rank: 305,
      semantic_rank: null,
      fused_rank: 2,
      rerank_rank: 2,
      scores: {},
      provenance: {},
    };
    const rows = candidatesFromPersistedPool([target, competitorA, competitorB], RRF_K);

    const example = findFusionDefectCase(rows);

    expect(example).not.toBeNull();
    expect(example!.target.productId).toBe(1);
    expect(example!.targetArm).toBe("semantic");
    expect(example!.competitor.productId).toBe(3);
    expect(example!.competitorWorstRank).toBe(305);
  });
});

describe("fusedToFinalGap", () => {
  function candidate(fusedRank: number, finalRank: number): FusionDefectCandidate {
    return { productId: 1, title: "x", fusedRank, finalRank, arms: [] };
  }

  it("flags a gap at the same threshold RepairEvidence.tsx uses", () => {
    expect(fusedToFinalGap(candidate(SUSPICIOUS_GAP_THRESHOLD + 2, 1)).suspicious).toBe(true);
    expect(fusedToFinalGap(candidate(SUSPICIOUS_GAP_THRESHOLD + 1, 1)).suspicious).toBe(true);
    expect(fusedToFinalGap(candidate(SUSPICIOUS_GAP_THRESHOLD, 1)).suspicious).toBe(false);
  });

  it("reports the raw position delta, not an absolute value", () => {
    expect(fusedToFinalGap(candidate(1, 5)).gap).toBe(-4);
    expect(fusedToFinalGap(candidate(5, 1)).gap).toBe(4);
  });
});
