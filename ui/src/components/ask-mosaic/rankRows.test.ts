import { describe, expect, it } from "vitest";
import type { RetrievalRunResponse, SearchResultEventRecord } from "../../types";
import { receiptCaption, receiptLegend, rowsFromReceipt, widestTotal } from "./rankRows";

// A value the saved search recorded about itself; the UI must print it, not supply its own.
const RECORDED_K = 61;

const row = (productId: number, overrides: Partial<SearchResultEventRecord> = {}): SearchResultEventRecord => ({
  product_id: productId,
  result_rank: productId,
  fts_rank: null,
  trigram_rank: null,
  semantic_rank: null,
  fused_rank: productId + 10,
  rerank_rank: null,
  scores: {},
  provenance: {},
  eligible: true,
  ...overrides,
});

function receipt(candidates: SearchResultEventRecord[]): RetrievalRunResponse {
  return {
    run: {
      search_event_id: "cc3a32d8-aaaa-bbbb-cccc-000000000000",
      occurred_at: "2026-10-04T00:00:00Z",
      session_id: null,
      query_text: "q",
      normalized_query: null,
      filters: {},
      retrieval_profile: { rrf_k: RECORDED_K },
      source_revision: null,
      embedding_model_id: null,
      rerank_model_id: "cohere.rerank-v3-5:0",
      retrieval_strategy: null,
      database_version: null,
      vector_extension_version: null,
      aurora_instance_class: null,
      hnsw_settings: {},
      candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 36, semantic_in_pool: 38 },
      total_latency_ms: 3540,
      diagnostics: {},
    },
    candidates,
  };
}

describe("rowsFromReceipt", () => {
  it("lists the top rows in final order with the ranks and contributions the database wrote", () => {
    const rows = rowsFromReceipt(
      receipt([
        row(3, { result_rank: 2 }),
        row(7, {
          result_rank: 1,
          fts_rank: 1,
          semantic_rank: 4,
          fused_rank: 2,
          scores: { rerank: 0.952 },
          provenance: { channels: { fts: { rrf_contribution: 0.0164 }, vector: { rrf_contribution: 0.0156 } } },
        }),
      ]),
      new Map([[7, "Steelcase Gesture"]]),
    );
    expect(rows.map((item) => item.productId)).toEqual([7, 3]);
    expect(rows[0]).toMatchObject({
      name: "Steelcase Gesture",
      final: 1,
      combined: 2,
      fts: 1,
      trigram: null,
      semantic: 4,
      rerank: 0.952,
      parts: { fts: 0.0164, trigram: 0, semantic: 0.0156 },
    });
    expect(rows[1].name).toBeNull();
  });

  it("keeps five rows and leaves out candidates the filters excluded", () => {
    const candidates = [
      ...Array.from({ length: 8 }, (_, index) => row(index + 1)),
      row(99, { result_rank: 0, eligible: false }),
    ];
    const rows = rowsFromReceipt(receipt(candidates), new Map());
    expect(rows).toHaveLength(5);
    expect(rows.map((item) => item.productId)).not.toContain(99);
  });

  it("sizes the widest bar from the recorded contributions, not from a constant", () => {
    const rows = rowsFromReceipt(
      receipt([
        row(1, { provenance: { channels: { fts: { rrf_contribution: 0.02 }, trigram: { rrf_contribution: 0.01 } } } }),
        row(2, { provenance: { channels: { fts: { rrf_contribution: 0.005 } } } }),
      ]),
      new Map(),
    );
    expect(widestTotal(rows)).toBeCloseTo(0.03);
  });
});

describe("receipt wording", () => {
  it("states the search, its time and the pool each method fed", () => {
    expect(receiptCaption("cc3a32d8-aaaa", receipt([]))).toBe(
      "Search cc3a32d8 · 3.5 s in the service · combined 50 from exact terms 1, close spelling 36, meaning 38",
    );
  });

  it("reads k and the reranker from the saved search, and never supplies its own", () => {
    expect(receiptLegend(receipt([]))).toBe(`RRF, k = ${RECORDED_K} · rerank cohere.rerank-v3-5:0`);
    const bare = receipt([]);
    bare.run.retrieval_profile = {};
    bare.run.rerank_model_id = null;
    expect(receiptLegend(bare)).toBe("");
  });
});
