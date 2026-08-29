import { describe, expect, it } from "vitest";
import {
  buildRetrievalMatrix,
  matrixSummary,
  nearMissPairs,
  sharedWords,
  trigramSimilarity,
  trigrams,
} from "./retrievalMatrix";
import { seedRun } from "./retrievalSeed";
import type { ProductSummary, ResultSignals, SearchResponse } from "./types";

function signals(overrides: Partial<ResultSignals> = {}): ResultSignals {
  return {
    fts: { rank: null, raw_score: null, rrf_contribution: null },
    trigram: { rank: null, raw_score: null, rrf_contribution: null },
    semantic: { rank: null, raw_score: null, rrf_contribution: null },
    rrf_score: 0,
    pre_rerank_rank: 1,
    pre_rerank_score: 0,
    rerank_score: null,
    final_rank: 1,
    score_semantics: "test",
    ...overrides,
  };
}

function product(
  productId: number,
  fields: Partial<ProductSummary>,
  resultSignals: ResultSignals,
): ProductSummary {
  return {
    product_id: productId,
    sku: `SKU-${productId}`,
    title: "Test Product",
    short_description: "",
    domain: "consumer_electronics",
    category_key: "over-ear-headphones",
    category_path: "Audio > Over-Ear Headphones",
    brand: "Testbrand",
    model: `M-${productId}`,
    price_cents: 10000,
    list_price_cents: 10000,
    currency: "USD",
    rating: 4.5,
    review_count: 10,
    availability: "in_stock",
    inventory_count: 5,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: false,
    is_retrieval_anchor: false,
    image_url: null,
    image_source: null,
    signals: resultSignals,
    sources: [],
    ...fields,
  };
}

// Restating the retrieval profile here would put a second copy of rrf_k and the
// arm limits in source, which scripts/config_tripwire.py forbids for good reason:
// db/config/retrieval.yaml is the one place those values are set. The committed
// capture already carries the profile its run used, so the fixtures borrow it.
const profile = seedRun.diagnostics!.retrieval_profile;

function response(results: ProductSummary[]): SearchResponse {
  return {
    search_event_id: "matrix-test",
    query: "test query",
    normalized_query: "test query",
    applied_filters: {},
    results,
    diagnostics: {
      strategy: "rrf_fusion+rerank",
      embedding_model_id: "us.cohere.embed-v4:0",
      embedding_dimensions: 1024,
      rerank_model_id: "cohere.rerank-v3-5:0",
      rerank_status: "applied",
      retrieval_profile: profile,
      candidate_counts: {},
      stage_timings_ms: {},
      total_latency_ms: 100,
    },
  };
}

describe("trigram arithmetic", () => {
  it("pads words the way pg_trgm does", () => {
    // show_trgm('cat') is {"  c"," ca","cat","at "}: two leading spaces, one
    // trailing. Any other padding produces a different similarity for every pair.
    expect([...trigrams("cat")].sort()).toEqual(["  c", " ca", "at ", "cat"]);
    expect(trigrams("headphones").size).toBe("headphones".length + 1);
  });

  it("reproduces similarity() values measured on the live cluster", () => {
    // Measured with `SELECT similarity(a, b)` on the workshop Aurora cluster.
    // These are the numbers Postgres returns, not a target chosen here.
    const measured: Array<[string, string, number]> = [
      ["hedphones", "headphones", 0.615385],
      ["wirless", "wireless", 0.545455],
      ["noice", "noise", 0.333333],
      ["canceling", "cancelling", 0.75],
      ["batery", "battery", 0.666667],
      ["cat", "hat", 0.142857],
    ];
    for (const [left, right, expected] of measured) {
      expect(trigramSimilarity(left, right)).toBeCloseTo(expected, 6);
    }
    expect(trigramSimilarity("noise", "noise")).toBe(1);
  });
});

describe("match reasons", () => {
  const headphones = product(
    2,
    {
      title: "Sonora WH-C720 Wireless Noise-Cancelling Headphones",
      brand: "Sonora",
      model: "WH-C720",
      tags: ["long battery life", "noise cancelling"],
    },
    signals(),
  );

  it("names only words a participant can see in the record", () => {
    const shared = sharedWords("wireless noise cancelling headphones", headphones);
    expect(shared).toEqual(["wireless", "noise", "cancelling", "headphones"]);
  });

  it("drops stopwords and bare amounts, which explain nothing", () => {
    expect(sharedWords("headphones under $200 with a long battery life", headphones))
      .toEqual(["headphones", "long", "battery", "life"]);
  });

  it("pairs each misspelling with the catalog word that repaired it", () => {
    const pairs = nearMissPairs("noice cancelng hedfones", headphones);
    // In query order, so the chip reads as the sentence that was typed. Every
    // token of the Lab 1 anchor is misspelled, so all three pair with the catalog
    // word they approximate -- one repair per word typed, which is what the
    // participant needs to see. The retired identity anchor produced only two
    // pairs and left the third word unexplained.
    expect(pairs).toEqual([
      { queryWord: "noice", productWord: "noise" },
      { queryWord: "cancelng", productWord: "cancelling" },
      { queryWord: "hedfones", productWord: "headphones" },
    ]);
  });

  it("reports nothing when every word already matches", () => {
    expect(nearMissPairs("wireless headphones", headphones)).toEqual([]);
  });
});

describe("before and after reranking", () => {
  it("compares positions among the shown rows, not fused-pool ranks", () => {
    // The load-bearing honesty property. These three rows sit at fused ranks 1,
    // 30 and 40 of a 50-candidate pool and come back in that same order, so
    // reranking changed nothing. Comparing pre_rerank_rank to final_rank directly
    // would report the last row as having climbed 37 places.
    const matrix = buildRetrievalMatrix(
      response([
        product(1, {}, signals({ semantic: { rank: 1, raw_score: 0.9, rrf_contribution: 0.0164 }, pre_rerank_rank: 1, final_rank: 1, rerank_score: 0.9 })),
        product(2, {}, signals({ semantic: { rank: 29, raw_score: 0.7, rrf_contribution: 0.0112 }, pre_rerank_rank: 30, final_rank: 2, rerank_score: 0.8 })),
        product(3, {}, signals({ semantic: { rank: 39, raw_score: 0.6, rrf_contribution: 0.0101 }, pre_rerank_rank: 40, final_rank: 3, rerank_score: 0.7 })),
      ]),
    );

    expect(matrix.rows.map((row) => row.beforeRank)).toEqual([1, 2, 3]);
    expect(matrix.rows.map((row) => row.movement)).toEqual([0, 0, 0]);
    expect(matrix.movedRows).toBe(0);
    expect(matrixSummary(matrix)).toContain("Reranking left the fused order unchanged");
    // The fused-pool position is still reported, because it is real.
    expect(matrix.rows.map((row) => row.fusedRank)).toEqual([1, 30, 40]);
    expect(matrix.rows[0].fusedPool).toBe(profile.fused_limit);
  });

  it("spends each column on a number no other column already shows", () => {
    // The fused column first showed the position among the shown rows, which is
    // the left half of Before / after, and the rerank column showed final_rank,
    // which is the row's own rank badge and the right half of Before / after. Two
    // of five columns were repeating their neighbours and the fused-pool position
    // — the interesting one — appeared nowhere.
    const matrix = buildRetrievalMatrix(
      response([
        product(1, {}, signals({
          semantic: { rank: 30, raw_score: 0.61, rrf_contribution: 0.0111 },
          pre_rerank_rank: 31,
          rrf_score: 0.0111,
          final_rank: 1,
          rerank_score: 0.7284,
        })),
      ]),
    );
    const [row] = matrix.rows;
    const [, , , fused, rerank] = row.cells;

    expect(fused.label).toBe("#31");
    expect(fused.label).not.toBe(`#${row.beforeRank}`);
    expect(fused.detail).toBe("0.01110");
    expect(rerank.label).toBe("0.7284");
    expect(rerank.label).not.toBe(`#${row.finalRank}`);
  });

  it("signs movement so a promotion and a demotion cannot be confused", () => {
    const matrix = buildRetrievalMatrix(
      response([
        product(1, {}, signals({ pre_rerank_rank: 9, final_rank: 1, rerank_score: 0.9 })),
        product(2, {}, signals({ pre_rerank_rank: 2, final_rank: 2, rerank_score: 0.8 })),
        product(3, {}, signals({ pre_rerank_rank: 1, final_rank: 3, rerank_score: 0.7 })),
      ]),
    );

    // Before: 1 -> product 3, 2 -> product 2, 3 -> product 1.
    expect(matrix.rows.map((row) => [row.product.product_id, row.movement])).toEqual([
      [1, 2],
      [2, 0],
      [3, -2],
    ]);
    expect(matrix.biggestRise).toBe(2);
    expect(matrix.biggestFall).toBe(-2);
    expect(matrix.movedRows).toBe(2);
  });
});

describe("column measures", () => {
  it("counts the rows each arm actually returned", () => {
    const matrix = buildRetrievalMatrix(
      response([
        product(1, {}, signals({
          fts: { rank: 1, raw_score: 0.03, rrf_contribution: 0.0164 },
          trigram: { rank: 1, raw_score: 0.8, rrf_contribution: 0.0164 },
          pre_rerank_rank: 1,
          final_rank: 1,
          rerank_score: 0.9,
        })),
        product(2, {}, signals({
          semantic: { rank: 5, raw_score: 0.7, rrf_contribution: 0.0154 },
          pre_rerank_rank: 6,
          final_rank: 2,
          rerank_score: 0.8,
        })),
        product(3, {}, signals({
          semantic: { rank: 9, raw_score: 0.6, rrf_contribution: 0.0145 },
          pre_rerank_rank: 10,
          final_rank: 3,
          rerank_score: 0.7,
        })),
      ]),
    );

    expect(matrix.columns.map((column) => `${column.label}: ${column.measure}`)).toEqual([
      // The five labels come from retrievalLanguage, so a column heading here and
      // a "Why this match" row in Shop cannot drift apart.
      "Exact terms: 1 of 3",
      "Close spelling: 1 of 3",
      "Meaning match: 2 of 3",
      `Before reranking: 3 of ${profile.fused_limit}`,
      // Not "Final position": this column's cells hold `rerank_score`, and a 0.9204
      // under a heading that promises a rank is the table lying about its units.
      "Rerank score: 0 of 3",
    ]);
    expect(matrix.columns[2].mechanism).toContain("1024d");
    expect(matrix.columns[3].mechanism).toContain(`k = ${profile.rrf_k}`);
  });

  it("says so when the reranker never ran, instead of implying it did", () => {
    const matrix = buildRetrievalMatrix(
      response([product(1, {}, signals({ semantic: { rank: 1, raw_score: 0.9, rrf_contribution: 0.0164 } }))]),
    );
    const rerank = matrix.columns[4];
    expect(rerank.measure).toBe("not applied");
    expect(matrix.rows[0].cells[4].missing).toBe(true);
    expect(matrix.rows[0].reasons.some((reason) => reason.kind === "rerank")).toBe(false);
  });
});

describe("row verdicts", () => {
  it("says a row shares no word with the query when it shares none", () => {
    const matrix = buildRetrievalMatrix(
      response([
        product(
          1,
          { title: "Aurora Desk Lamp", brand: "Aurora", model: "DL-1" },
          signals({
            semantic: { rank: 4, raw_score: 0.61, rrf_contribution: 0.0156 },
            pre_rerank_rank: 4,
            final_rank: 1,
            rerank_score: 0.6,
          }),
        ),
      ]),
    );
    expect(matrix.rows[0].verdict).toBe(
      "Only the vector arm found it: it shares no word with the query.",
    );
    expect(matrix.rows[0].reasons.map((reason) => reason.label)).toContain(
      "No query word in this record; nearest by meaning",
    );
  });

  it("names every arm that reported the row", () => {
    const matrix = buildRetrievalMatrix(
      response([
        product(1, {}, signals({
          fts: { rank: 1, raw_score: 0.03, rrf_contribution: 0.0164 },
          trigram: { rank: 1, raw_score: 0.8, rrf_contribution: 0.0164 },
          semantic: { rank: 1, raw_score: 0.9, rrf_contribution: 0.0164 },
          final_rank: 1,
          rerank_score: 0.9,
        })),
      ]),
    );
    expect(matrix.rows[0].verdict).toBe(
      "Found by exact words, close spelling and meaning.",
    );
  });
});

describe("the committed capture through the matrix", () => {
  it("produces a matrix whose column measures agree with its own rows", () => {
    const matrix = buildRetrievalMatrix(seedRun, [2]);
    expect(matrix.rows).toHaveLength(seedRun.results.length);

    const arms = ["fts", "trigram", "semantic"] as const;
    arms.forEach((arm, index) => {
      const counted = seedRun.results.filter(
        (candidate) => candidate.signals![arm].rank !== null,
      ).length;
      expect(matrix.columns[index].measure).toBe(`${counted} of ${matrix.rows.length}`);
    });

    // The scenario target is marked in place rather than pulled into a side panel.
    expect(matrix.rows.filter((row) => row.isTarget).map((row) => row.product.product_id))
      .toEqual([2]);
    // Before/after stays inside the shown set, whatever the fused pool did.
    matrix.rows.forEach((row) => {
      expect(row.beforeRank).toBeGreaterThanOrEqual(1);
      expect(row.beforeRank).toBeLessThanOrEqual(matrix.rows.length);
    });
  });
});
