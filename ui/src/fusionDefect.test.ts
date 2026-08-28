import { describe, expect, it } from "vitest";
import {
  armContribution,
  brokenOrder,
  candidatesFromPersistedPool,
  candidatesFromResults,
  findFusionDefectCase,
  findTieCollapseExample,
  fusedToFinalGap,
  invertedPairCount,
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
 * product 4 (fts_rank 3, trigram_rank 4) sits at fused rank 4, above product
 * 14552's fused rank 8, even though product 14552 is a genuine single-arm
 * rank-1 result. That looks like the fusion defect, but it is not one:
 * correct RRF agrees with the broken formula on this pair (0.031498 for
 * product 4 vs. 0.016393 for product 14552 -- product 4 wins under both).
 * `findFusionDefectCase` must reject this exact shape, which is the
 * regression a prior version of this module shipped.
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

/**
 * The real fused pool behind Lab 2's own mission query, exactly as persisted.
 * Reproduced independently against the live app (`GET
 * /api/retrieval/events/d0bf0b73-4c69-4f81-bd5e-ed07960957a4`) before writing
 * any test against it -- these are not invented numbers:
 *
 *   query: "ergonomic mesh chair for long workdays with adjustable lumbar
 *   support" (mission G-008), filters { domain: "home_office",
 *   in_stock_only: true, attributes: { seat_depth_adjustable: true } },
 *   rerank: false, `rrf_k` 60, 50 candidates.
 *
 * arm-count histogram { 3: 1, 2: 1, 1: 48 }: product 370002 holds all three
 * arms, product 370001 holds two, and the other 48 hold exactly one each
 * (all `semantic_rank`, spanning source rank 3 to 50). That is exactly 3
 * distinct broken scores across the whole pool, and the 48-member tie group
 * is where `mosaic_search.search_hybrid_rrf`'s own `ORDER BY e.rrf_score
 * DESC, e.product_id` (`db/sql/09_search_functions.sql:515`) resolves the
 * broken formula's identical scores by ascending product_id -- not by any
 * of those 48 candidates' real measured ranks. Verified: product 372781
 * (truly ranked #48) sits at broken rank #4, ahead of product 374621 (truly
 * ranked #4) at broken rank #5, purely because 372781 < 374621. 538 pairs
 * across the pool land in the opposite order from the real measured one.
 */
const CHAIR_POOL: SearchResultEventRecord[] = [
  { product_id: 370002, result_rank: 1, fts_rank: 1, trigram_rank: 1, semantic_rank: 1, fused_rank: 1, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370001, result_rank: 2, fts_rank: 2, trigram_rank: null, semantic_rank: 2, fused_rank: 2, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370093, result_rank: 3, fts_rank: null, trigram_rank: null, semantic_rank: 3, fused_rank: 3, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 374621, result_rank: 4, fts_rank: null, trigram_rank: null, semantic_rank: 4, fused_rank: 4, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 375374, result_rank: 5, fts_rank: null, trigram_rank: null, semantic_rank: 5, fused_rank: 5, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370242, result_rank: 6, fts_rank: null, trigram_rank: null, semantic_rank: 6, fused_rank: 6, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371501, result_rank: 7, fts_rank: null, trigram_rank: null, semantic_rank: 7, fused_rank: 7, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 391847, result_rank: 8, fts_rank: null, trigram_rank: null, semantic_rank: 8, fused_rank: 8, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 375821, result_rank: 9, fts_rank: null, trigram_rank: null, semantic_rank: 9, fused_rank: 9, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370402, result_rank: 10, fts_rank: null, trigram_rank: null, semantic_rank: 10, fused_rank: 10, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 375454, result_rank: 11, fts_rank: null, trigram_rank: null, semantic_rank: 11, fused_rank: 11, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 378408, result_rank: 12, fts_rank: null, trigram_rank: null, semantic_rank: 12, fused_rank: 12, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 385521, result_rank: 13, fts_rank: null, trigram_rank: null, semantic_rank: 13, fused_rank: 13, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371421, result_rank: 14, fts_rank: null, trigram_rank: null, semantic_rank: 14, fused_rank: 14, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 375338, result_rank: 15, fts_rank: null, trigram_rank: null, semantic_rank: 15, fused_rank: 15, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 377281, result_rank: 16, fts_rank: null, trigram_rank: null, semantic_rank: 16, fused_rank: 16, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 376206, result_rank: 17, fts_rank: null, trigram_rank: null, semantic_rank: 17, fused_rank: 17, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 377154, result_rank: 18, fts_rank: null, trigram_rank: null, semantic_rank: 18, fused_rank: 18, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 376523, result_rank: 19, fts_rank: null, trigram_rank: null, semantic_rank: 19, fused_rank: 19, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 391242, result_rank: 20, fts_rank: null, trigram_rank: null, semantic_rank: 20, fused_rank: 20, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 374493, result_rank: 21, fts_rank: null, trigram_rank: null, semantic_rank: 21, fused_rank: 21, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371765, result_rank: 22, fts_rank: null, trigram_rank: null, semantic_rank: 22, fused_rank: 22, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 376885, result_rank: 23, fts_rank: null, trigram_rank: null, semantic_rank: 23, fused_rank: 23, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 373682, result_rank: 24, fts_rank: null, trigram_rank: null, semantic_rank: 24, fused_rank: 24, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370416, result_rank: 25, fts_rank: null, trigram_rank: null, semantic_rank: 25, fused_rank: 25, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 373842, result_rank: 26, fts_rank: null, trigram_rank: null, semantic_rank: 26, fused_rank: 26, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 391685, result_rank: 27, fts_rank: null, trigram_rank: null, semantic_rank: 27, fused_rank: 27, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371053, result_rank: 28, fts_rank: null, trigram_rank: null, semantic_rank: 28, fused_rank: 28, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 378481, result_rank: 29, fts_rank: null, trigram_rank: null, semantic_rank: 29, fused_rank: 29, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 374845, result_rank: 30, fts_rank: null, trigram_rank: null, semantic_rank: 30, fused_rank: 30, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 375697, result_rank: 31, fts_rank: null, trigram_rank: null, semantic_rank: 31, fused_rank: 31, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370009, result_rank: 32, fts_rank: null, trigram_rank: null, semantic_rank: 32, fused_rank: 32, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 372906, result_rank: 33, fts_rank: null, trigram_rank: null, semantic_rank: 33, fused_rank: 33, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371522, result_rank: 34, fts_rank: null, trigram_rank: null, semantic_rank: 34, fused_rank: 34, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370218, result_rank: 35, fts_rank: null, trigram_rank: null, semantic_rank: 35, fused_rank: 35, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 376721, result_rank: 36, fts_rank: null, trigram_rank: null, semantic_rank: 36, fused_rank: 36, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 378805, result_rank: 37, fts_rank: null, trigram_rank: null, semantic_rank: 37, fused_rank: 37, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 373101, result_rank: 38, fts_rank: null, trigram_rank: null, semantic_rank: 38, fused_rank: 38, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371453, result_rank: 39, fts_rank: null, trigram_rank: null, semantic_rank: 39, fused_rank: 39, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 370203, result_rank: 40, fts_rank: null, trigram_rank: null, semantic_rank: 40, fused_rank: 40, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 373887, result_rank: 41, fts_rank: null, trigram_rank: null, semantic_rank: 41, fused_rank: 41, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 378813, result_rank: 42, fts_rank: null, trigram_rank: null, semantic_rank: 42, fused_rank: 42, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371908, result_rank: 43, fts_rank: null, trigram_rank: null, semantic_rank: 43, fused_rank: 43, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 371799, result_rank: 44, fts_rank: null, trigram_rank: null, semantic_rank: 44, fused_rank: 44, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 372381, result_rank: 45, fts_rank: null, trigram_rank: null, semantic_rank: 45, fused_rank: 45, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 377395, result_rank: 46, fts_rank: null, trigram_rank: null, semantic_rank: 46, fused_rank: 46, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 393013, result_rank: 47, fts_rank: null, trigram_rank: null, semantic_rank: 47, fused_rank: 47, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 372781, result_rank: 48, fts_rank: null, trigram_rank: null, semantic_rank: 48, fused_rank: 48, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 385843, result_rank: 49, fts_rank: null, trigram_rank: null, semantic_rank: 49, fused_rank: 49, rerank_rank: null, scores: {}, provenance: {} },
  { product_id: 378561, result_rank: 50, fts_rank: null, trigram_rank: null, semantic_rank: 50, fused_rank: 50, rerank_rank: null, scores: {}, provenance: {} },
];

describe("brokenOrder", () => {
  /**
   * The required proof, isolated from the 50-row measured pool below: three
   * single-arm candidates, same arm count, deliberately arranged so ascending
   * `product_id` is *not* the real measured order. `mosaic_search.search_hybrid_rrf`
   * (`db/sql/09_search_functions.sql:515`) breaks a broken-score tie by
   * ascending `product_id`; this proves this function reproduces exactly
   * that, rather than leaving the tie in input order or some other rule.
   */
  it("resolves an equal-arm-count tie to ascending product_id, which is not the real measured order", () => {
    const pool: SearchResultEventRecord[] = [
      { product_id: 300, result_rank: 2, fts_rank: null, trigram_rank: null, semantic_rank: 40, fused_rank: 2, rerank_rank: null, scores: {}, provenance: {} },
      { product_id: 100, result_rank: 1, fts_rank: null, trigram_rank: null, semantic_rank: 5, fused_rank: 1, rerank_rank: null, scores: {}, provenance: {} },
      { product_id: 200, result_rank: 3, fts_rank: null, trigram_rank: null, semantic_rank: 20, fused_rank: 3, rerank_rank: null, scores: {}, provenance: {} },
    ];
    const rows = candidatesFromPersistedPool(pool, RRF_K);

    // Witness: all three genuinely tie on the broken score (same arm count).
    const ranked = brokenOrder(rows);
    expect(new Set(ranked.map((r) => r.brokenScore)).size).toBe(1);

    // Broken order is ascending product_id: 100, 200, 300.
    expect(ranked.map((r) => r.candidate.productId)).toEqual([100, 200, 300]);

    // The real measured order (by fused_rank, i.e. what search_hybrid_rrf
    // actually reported) is 100, 300, 200 -- not ascending product_id, so
    // the broken order agreeing with product_id is not "coincidentally right."
    const realOrder = [...rows]
      .sort((a, b) => a.fusedRank - b.fusedRank)
      .map((c) => c.productId);
    expect(realOrder).toEqual([100, 300, 200]);
    expect(ranked.map((r) => r.candidate.productId)).not.toEqual(realOrder);
  });
});

describe("findTieCollapseExample / invertedPairCount", () => {
  it("reproduces the measured chair-mission pool's tie collapse exactly", () => {
    const rows = candidatesFromPersistedPool(CHAIR_POOL, RRF_K);

    // Witness, independent of the function's own verdict: the measured
    // arm-count histogram, read directly off the fixture.
    const armCounts = rows.map(
      (row) => row.arms.filter((arm) => arm.sourceRank !== null).length,
    );
    expect(armCounts.filter((n) => n === 1)).toHaveLength(48);
    expect(armCounts.filter((n) => n === 2)).toHaveLength(1);
    expect(armCounts.filter((n) => n === 3)).toHaveLength(1);

    const tie = findTieCollapseExample(rows);

    expect(tie).not.toBeNull();
    expect(tie!.poolSize).toBe(50);
    expect(tie!.distinctBrokenScores).toBe(3);
    expect(tie!.tieGroupSize).toBe(48);
    expect(tie!.invertedPairs).toBe(538);

    // The specific pair: smaller product_id, truly ranked far worse, sits
    // ahead under the broken formula's tiebreak.
    expect(tie!.first.candidate.productId).toBe(372781);
    expect(tie!.first.candidate.fusedRank).toBe(48);
    expect(tie!.second.candidate.productId).toBe(374621);
    expect(tie!.second.candidate.fusedRank).toBe(4);
    expect(tie!.first.brokenRank).toBeLessThan(tie!.second.brokenRank);
    expect(tie!.first.brokenScore).toBe(tie!.second.brokenScore);
  });

  it("names the same broken-vs-real disagreement invertedPairCount counts directly", () => {
    const rows = candidatesFromPersistedPool(CHAIR_POOL, RRF_K);
    const ranked = brokenOrder(rows);
    expect(invertedPairCount(ranked)).toBe(538);
  });

  it("returns null when no two candidates share an arm count", () => {
    const distinctArmCounts: SearchResultEventRecord[] = [
      { product_id: 1, result_rank: 1, fts_rank: 1, trigram_rank: 1, semantic_rank: 1, fused_rank: 1, rerank_rank: null, scores: {}, provenance: {} },
      { product_id: 2, result_rank: 2, fts_rank: 2, trigram_rank: null, semantic_rank: null, fused_rank: 2, rerank_rank: null, scores: {}, provenance: {} },
    ];
    const rows = candidatesFromPersistedPool(distinctArmCounts, RRF_K);
    expect(findTieCollapseExample(rows)).toBeNull();
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
