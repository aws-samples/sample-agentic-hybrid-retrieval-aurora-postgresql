import { describe, expect, it } from "vitest";
import {
  buildRepairEvidence,
  isPlausibleSearchEventId,
  RANK_UNCHANGED_REASSURANCE,
  SUSPICIOUS_GAP_THRESHOLD,
} from "./repairEvidence";
import type {
  RetrievalRunResponse,
  SearchEventRecord,
  SearchResultEventRecord,
} from "./types";

/**
 * The measured Lab 1 pair, exactly as pulled from the live cluster:
 *
 *   BEFORE 9f92f8cc-efc2-4d81-a94a-69638d050282  fts=1 trg=0 sem=49 pool=50
 *          product 2: fts_rank=1 trigram_rank=NULL fused_rank=1 rerank_rank=1
 *          result_rank=1
 *   AFTER  9614ed9b-4ceb-4aad-9276-4e69af2231b9  fts=1 trg=1 sem=49 pool=50
 *          product 2: fts_rank=1 trigram_rank=1 fused_rank=1 rerank_rank=1
 *          result_rank=1
 *
 * The target ranks first both before and after, and fused/final are identical.
 * The only measured change is trigram_in_pool 0 -> 1 and the target's own
 * trigram_rank absent -> #1.
 */

function runRecord(overrides: Partial<SearchEventRecord> = {}): SearchEventRecord {
  return {
    search_event_id: "00000000-0000-4000-8000-000000000000",
    occurred_at: "2026-08-23T21:09:45.604925Z",
    session_id: null,
    query_text: "Sonorra WHC720",
    normalized_query: "Sonorra WHC720",
    filters: {},
    retrieval_profile: {},
    source_revision: "d8895cd6d88d20640d5fa518486668e98e788224",
    embedding_model_id: "us.cohere.embed-v4:0",
    rerank_model_id: "cohere.rerank-v3-5:0",
    retrieval_strategy: "rrf_fusion+rerank+exact_sku_preservation",
    database_version: "18.3",
    vector_extension_version: "0.8.1",
    aurora_instance_class: null,
    hnsw_settings: {},
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 0, semantic_in_pool: 49 },
    total_latency_ms: 785,
    diagnostics: {},
    ...overrides,
  };
}

function candidate(
  overrides: Partial<SearchResultEventRecord> = {},
): SearchResultEventRecord {
  return {
    product_id: 2,
    result_rank: 1,
    fts_rank: 1,
    trigram_rank: null,
    semantic_rank: null,
    fused_rank: 1,
    rerank_rank: 1,
    scores: {},
    provenance: {},
    ...overrides,
  };
}

function run(
  eventOverrides: Partial<SearchEventRecord>,
  candidates: SearchResultEventRecord[],
): RetrievalRunResponse {
  return { run: runRecord(eventOverrides), candidates };
}

const LAB1_BEFORE = run(
  {
    search_event_id: "9f92f8cc-efc2-4d81-a94a-69638d050282",
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 0, semantic_in_pool: 49 },
  },
  [candidate({ trigram_rank: null })],
);

const LAB1_AFTER = run(
  {
    search_event_id: "9614ed9b-4ceb-4aad-9276-4e69af2231b9",
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 1, semantic_in_pool: 49 },
  },
  [candidate({ trigram_rank: 1 })],
);

describe("buildRepairEvidence — measured Lab 1 pair", () => {
  it("shows the trigram arm's participation moving 0 -> 1", () => {
    const evidence = buildRepairEvidence(LAB1_BEFORE, LAB1_AFTER);
    const trigram = evidence.armDeltas.find((delta) => delta.arm === "trigram");

    expect(trigram?.beforeInPool).toBe(0);
    expect(trigram?.afterInPool).toBe(1);
    expect(trigram?.beforeTargetRank).toBe("absent");
    expect(trigram?.afterTargetRank).toBe(1);
    // The other two arms did not move, which is what makes the trigram move legible.
    const fts = evidence.armDeltas.find((delta) => delta.arm === "fts");
    const semantic = evidence.armDeltas.find((delta) => delta.arm === "semantic");
    expect(fts?.beforeInPool).toBe(1);
    expect(fts?.afterInPool).toBe(1);
    expect(semantic?.beforeInPool).toBe(49);
    expect(semantic?.afterInPool).toBe(49);
  });

  it("reports the fused and final rank as unchanged, #1 both times", () => {
    const evidence = buildRepairEvidence(LAB1_BEFORE, LAB1_AFTER);

    expect(evidence.fused).toEqual({ before: 1, after: 1 });
    expect(evidence.final).toEqual({ before: 1, after: 1 });
  });

  it("marks the unchanged rank as confirmation, never as a failed repair", () => {
    // This is the assertion the spec calls out by name: a rank-only reading of
    // this pair shows nothing happened, and the surface must not let that reading
    // stand as "the repair failed." `rankUnchanged` is the flag the component
    // renders RANK_UNCHANGED_REASSURANCE from — asserting the flag AND the exact
    // copy is what pins the framing, not just the numbers.
    const evidence = buildRepairEvidence(LAB1_BEFORE, LAB1_AFTER);

    expect(evidence.rankUnchanged).toBe(true);
    expect(RANK_UNCHANGED_REASSURANCE).not.toMatch(/no change|nothing (was|happened)|the repair failed/i);
    expect(RANK_UNCHANGED_REASSURANCE).toMatch(/not a failed repair/i);
  });

  it("does not report the rank as unchanged when there is no before to compare", () => {
    // Independence check in the other direction: hasBefore alone must gate
    // rankUnchanged, not the shape of the after run.
    const evidence = buildRepairEvidence(null, LAB1_AFTER);

    expect(evidence.hasBefore).toBe(false);
    expect(evidence.rankUnchanged).toBe(false);
  });

  it("is independent of fields that carry no retrieval information", () => {
    // Same shape, different session_id / occurred_at / query text. The verdict
    // must not move: it is keyed on candidate_counts and per-arm ranks, not on
    // incidental metadata that happens to differ between two real database rows.
    const before = run(
      {
        search_event_id: LAB1_BEFORE.run.search_event_id,
        session_id: "some-other-session",
        occurred_at: "2020-01-01T00:00:00Z",
        query_text: "a completely different query",
        candidate_counts: LAB1_BEFORE.run.candidate_counts,
      },
      LAB1_BEFORE.candidates,
    );
    const after = run(
      {
        search_event_id: LAB1_AFTER.run.search_event_id,
        session_id: "canonical-release-eval",
        occurred_at: "2099-12-31T23:59:59Z",
        query_text: "a completely different query",
        candidate_counts: LAB1_AFTER.run.candidate_counts,
      },
      LAB1_AFTER.candidates,
    );

    const evidence = buildRepairEvidence(before, after);
    const trigram = evidence.armDeltas.find((delta) => delta.arm === "trigram");

    expect(trigram?.beforeInPool).toBe(0);
    expect(trigram?.afterInPool).toBe(1);
    expect(evidence.rankUnchanged).toBe(true);
  });
});

describe("buildRepairEvidence — fused-to-final gap", () => {
  it("flags the measured 675825de shape (fused 49 -> final 1) as suspicious", () => {
    const after = run(
      { candidate_counts: { fused_pool: 50, fts_in_pool: 18, trigram_in_pool: 18, semantic_in_pool: 19 } },
      [candidate({ product_id: 211896, result_rank: 1, fused_rank: 49, fts_rank: 73, trigram_rank: null, semantic_rank: 114 })],
    );

    const evidence = buildRepairEvidence(null, after);

    expect(evidence.afterGap.fusedRank).toBe(49);
    expect(evidence.afterGap.finalRank).toBe(1);
    expect(evidence.afterGap.gap).toBe(48);
    expect(evidence.afterGap.suspicious).toBe(true);
  });

  it("does not flag the measured Lab 1 pair's zero-gap shape", () => {
    const evidence = buildRepairEvidence(LAB1_BEFORE, LAB1_AFTER);

    expect(evidence.afterGap.gap).toBe(0);
    expect(evidence.afterGap.suspicious).toBe(false);
  });

  it("treats the threshold as the exact boundary, not merely 'large'", () => {
    // gap == threshold - 1: not suspicious.
    const small = run({}, [candidate({ fused_rank: SUSPICIOUS_GAP_THRESHOLD, result_rank: 1 })]);
    expect(buildRepairEvidence(null, small).afterGap.suspicious).toBe(false);

    // gap == threshold: suspicious.
    const atThreshold = run({}, [
      candidate({ fused_rank: SUSPICIOUS_GAP_THRESHOLD + 1, result_rank: 1 }),
    ]);
    expect(buildRepairEvidence(null, atThreshold).afterGap.suspicious).toBe(true);
    expect(buildRepairEvidence(null, atThreshold).afterGap.gap).toBe(SUSPICIOUS_GAP_THRESHOLD);
  });

  it("cannot compute a gap when the target is absent from the fused pool", () => {
    const after = run({}, [candidate({ fused_rank: null, result_rank: 1 })]);
    const evidence = buildRepairEvidence(null, after);

    expect(evidence.afterGap.fusedRank).toBe("absent");
    expect(evidence.afterGap.gap).toBeNull();
    expect(evidence.afterGap.suspicious).toBe(false);
  });
});

describe("buildRepairEvidence — missing before and missing target", () => {
  it("reports null, not zero, for every before-side figure when there is no before", () => {
    const evidence = buildRepairEvidence(null, LAB1_AFTER);

    expect(evidence.hasBefore).toBe(false);
    expect(evidence.fused.before).toBeNull();
    expect(evidence.final.before).toBeNull();
    expect(evidence.armDeltas.every((delta) => delta.beforeInPool === null)).toBe(true);
    expect(evidence.armDeltas.every((delta) => delta.beforeTargetRank === null)).toBe(true);
  });

  it("reports the target absent from a before run that never carried it", () => {
    const before = run(
      { candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 0, semantic_in_pool: 49 } },
      [candidate({ product_id: 999999 })],
    );
    const evidence = buildRepairEvidence(before, LAB1_AFTER);

    expect(evidence.fused.before).toBe("absent");
    expect(evidence.final.before).toBe("absent");
  });

  it("reports no target rather than guessing when the after run served nothing", () => {
    const after = run({}, []);
    const evidence = buildRepairEvidence(null, after);

    expect(evidence.targetProductId).toBeNull();
    expect(evidence.armDeltas.every((delta) => delta.afterTargetRank === "absent")).toBe(true);
    expect(evidence.afterGap.gap).toBeNull();
  });
});

describe("isPlausibleSearchEventId", () => {
  it("accepts a UUID, including with surrounding whitespace", () => {
    expect(isPlausibleSearchEventId("9f92f8cc-efc2-4d81-a94a-69638d050282")).toBe(true);
    expect(isPlausibleSearchEventId("  9f92f8cc-efc2-4d81-a94a-69638d050282  ")).toBe(true);
  });

  it("rejects prose, empty input, and near-misses", () => {
    expect(isPlausibleSearchEventId("")).toBe(false);
    expect(isPlausibleSearchEventId("not-a-uuid")).toBe(false);
    expect(isPlausibleSearchEventId("9f92f8cc-efc2-4d81-a94a-69638d05028")).toBe(false);
  });
});
