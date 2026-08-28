import { describe, expect, it } from "vitest";
import {
  armContribution,
  candidatesFromPersistedPool,
  candidatesFromResults,
  findCompetitorAboveTarget,
  fusedToFinalGap,
  type FusionDefectCandidate,
} from "./fusionDefect";
import { SUSPICIOUS_GAP_THRESHOLD } from "./repairEvidence";
import type { ProductSummary, ResultSignals, SearchResultEventRecord } from "./types";

/**
 * Measured live pair, query "noise cancelling headphones",
 * search_event_id 8cb50318-c61a-42c8-bf6c-5df9dc229983, `rrf_k` 60:
 *
 *   product 4    (Halo Comfort SE): fts_rank 3, trigram_rank 4, fused_rank 4
 *   product 14552 (NovaLogic OH-K044): semantic_rank 1, fused_rank 8
 *
 * Product 4 holds no rank-1 arm rank of its own and is present in two arms;
 * product 14552 is a genuine single-arm rank-1 result. Product 4 still sits
 * above it in the fused order this run actually reported. This is the
 * pairing `findCompetitorAboveTarget` exists to name.
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

describe("findCompetitorAboveTarget", () => {
  it("names the measured pair: product 4 outranks the rank-1 single-arm product 14552", () => {
    // Witness that the search actually considered more than the one pair it
    // found -- a literal on the fixture, independent of the function's own
    // verdict, per house rule 7.
    expect(POOL).toHaveLength(6);

    const rows = candidatesFromPersistedPool(POOL, RRF_K);
    const example = findCompetitorAboveTarget(rows);

    expect(example).not.toBeNull();
    expect(example!.target.productId).toBe(14552);
    expect(example!.targetArm).toBe("semantic");
    expect(example!.competitor.productId).toBe(4);
    expect(example!.competitorWorstRank).toBe(4);
  });

  it("is red at birth: fails once the target's rank-1 fact is corrupted to rank 2", () => {
    // The exact edit `findCompetitorAboveTarget` exists to catch: a target
    // that no longer truly holds rank 1 in its one arm must stop qualifying.
    const corrupted = POOL.map((row) =>
      row.product_id === 14552 ? { ...row, semantic_rank: 2 } : row);
    const rows = candidatesFromPersistedPool(corrupted, RRF_K);
    const example = findCompetitorAboveTarget(rows);
    expect(example).toBeNull();
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
    expect(findCompetitorAboveTarget(rows)).toBeNull();
  });

  it("keeps the competitor with the worse individual rank when more than one qualifies", () => {
    const extraCompetitor: SearchResultEventRecord = {
      product_id: 9001,
      result_rank: 2,
      fts_rank: 40,
      trigram_rank: 41,
      semantic_rank: null,
      fused_rank: 2,
      rerank_rank: 2,
      scores: {},
      provenance: {},
    };
    const rows = candidatesFromPersistedPool([...POOL, extraCompetitor], RRF_K);
    const example = findCompetitorAboveTarget(rows);
    expect(example!.competitor.productId).toBe(9001);
    expect(example!.competitorWorstRank).toBe(41);
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
