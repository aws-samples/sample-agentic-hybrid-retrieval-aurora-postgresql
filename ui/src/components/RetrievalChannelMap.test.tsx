// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { readChannels, RetrievalChannelMap } from "./RetrievalChannelMap";
import type {
  ReadinessResponse,
  RetrievalDiagnostics,
  SearchResponse,
} from "../types";

/**
 * Lab 1's whole lesson is that a component can be healthy while the composition
 * using it is broken, and these tests hold the two facts apart.
 *
 * `make reset-lab-1` deletes the `typo` CTE from
 * `mosaic_search.search_hybrid_rrf` and deliberately leaves
 * `mosaic_search.search_trigram` installed and callable, so the trigram GIN index
 * is present and valid in both states while `trigram_in_pool` flips from non-zero
 * to zero. A surface that reports only the second teaches a participant to go
 * looking for `CREATE EXTENSION`.
 *
 * The third state matters as much as the first two: `trigram_in_pool = 0` on a
 * query with no near-miss spellings is the arm having nothing to say, and calling
 * that "disconnected" would be a claim the response cannot support.
 */

function diagnostics(
  counts: Record<string, number>,
): NonNullable<SearchResponse["diagnostics"]> {
  return {
    strategy: "hybrid",
    embedding_model_id: "us.cohere.embed-v4:0",
    embedding_dimensions: 1024,
    rerank_model_id: "cohere.rerank-v3-5:0",
    rerank_status: "applied",
    retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
    candidate_counts: counts,
    stage_timings_ms: {},
    total_latency_ms: 120,
  };
}

function response(counts: Record<string, number>): SearchResponse {
  return {
    search_event_id: "channel-test",
    query: "noice cancelng hedfones",
    normalized_query: "noice cancelng hedfones",
    applied_filters: {},
    results: [],
    diagnostics: diagnostics(counts),
  };
}

function readiness(missingIndexes: string[] | null): ReadinessResponse {
  return {
    status: "ready",
    database_ready: true,
    model_space_ready: true,
    database: {
      database_name: "mosaic",
      server_version: "16.4",
      schema_ready: true,
      vector_version: "0.8.0",
      product_count: 500_000,
      embedded_product_count: 500_000,
      embedding_dimensions: 1024,
      embedding_model_ids: ["us.cohere.embed-v4:0"],
      premium_product_count: 120,
      evidence_product_count: 120,
      missing_retrieval_indexes: missingIndexes,
      missing_retrieval_functions: null,
    },
    configured_models: {
      embedding: "us.cohere.embed-v4:0",
      rerank: "cohere.rerank-v3-5:0",
      agent: "agent",
      synthesis: "synthesis",
    },
    bedrock_credentials: { ready: true },
  };
}

/** The canonical Lab 1 scenario's own `expected_techniques`. */
const REQUIRES_TRIGRAM = ["pg_trgm", "vector", "filters", "rrf"];

describe("readChannels", () => {
  afterEach(cleanup);

  it("explains what happened and when each retrieval method helps", () => {
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 5,
        trigram_in_pool: 4,
        semantic_in_pool: 10,
      }),
      REQUIRES_TRIGRAM,
      readiness([]),
    );

render(<RetrievalChannelMap readings={readings} />);

    expect(
      screen.getByRole("heading", {
        name: "Three ways Aurora looked for the same product",
      }),
    ).toBeTruthy();
    expect(screen.getAllByText("What happened")).toHaveLength(3);
    expect(screen.getAllByText("When this helps")).toHaveLength(3);
    expect(screen.getByText("5 of 12 candidates")).toBeTruthy();
    expect(
      screen.getByText(/words a shopper typed already appear in the catalog/i),
    ).toBeTruthy();
  });

  it("reports every arm as contributing with its share of the pool", () => {
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 5,
        trigram_in_pool: 4,
        semantic_in_pool: 10,
      }),
      REQUIRES_TRIGRAM,
      readiness(null),
    );

    expect(readings.map((reading) => reading.state)).toEqual([
      "contributing",
      "contributing",
      "contributing",
    ]);
    expect(readings.map((reading) => reading.inPool)).toEqual([5, 4, 10]);
    expect(readings.every((reading) => reading.pool === 12)).toBe(true);
    expect(readings.map((reading) => reading.label)).toEqual([
      "Exact terms",
      "Close spelling",
      "Meaning match",
    ]);
    expect(readings.map((reading) => reading.mechanism)).toEqual([
      "PostgreSQL Full-Text Search",
      "pg_trgm",
      "pgvector / HNSW",
    ]);
  });

  it("names the Postgres index and the purpose of every arm, healthy or not", () => {
    // The gap this closes: before, `indexName` only ever reached the screen
    // inside the broken-arm split, and nothing said what an arm was for. Both
    // must be present for every arm in the ordinary, nothing-broken state, not
    // only when a required arm is disconnected.
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 5,
        trigram_in_pool: 4,
        semantic_in_pool: 10,
      }),
      [],
      readiness([]),
    );

    expect(readings.map((reading) => reading.indexName)).toEqual([
      "product_document_fts_gin_idx",
      "product_document_trigram_gin_idx",
      "product_document_embedding_hnsw_cosine_idx",
    ]);
    expect(readings.map((reading) => reading.purpose)).toEqual([
      "Wins when the words a shopper typed already appear in the catalog, such as a model name or a brand.",
      "Earns its place when those words are misspelled or a variant, so character overlap finds what exact matching missed.",
      "Answers a described benefit or intent that shares no words with the product text at all.",
    ]);
    // Every arm is contributing, none disconnected: this is the healthy state,
    // and the two facts above hold in it exactly as they hold in the broken one.
    expect(readings.every((reading) => reading.state === "contributing")).toBe(true);
  });

  it("calls the required arm disconnected while its index stays healthy", () => {
    // The measured Lab 1 broken state: the trigram GIN index is present and valid,
    // and no candidate in the pool carries a trigram rank.
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 5,
        trigram_in_pool: 0,
        semantic_in_pool: 10,
      }),
      REQUIRES_TRIGRAM,
      readiness(null),
    );
    const trigram = readings[1];

    expect(trigram.state).toBe("disconnected");
    expect(trigram.indexHealthy).toBe(true);
    expect(trigram.indexName).toBe("product_document_trigram_gin_idx");
    // The other two are unaffected, which is what makes the one failure legible.
    expect(readings[0].state).toBe("contributing");
    expect(readings[2].state).toBe("contributing");
  });

  it("does not call an arm disconnected when the scenario never required it", () => {
    // An exactly-spelled query can legitimately produce nothing above the trigram
    // threshold. That is the arm having nothing to say, not the arm being unwired,
    // and this response cannot tell the difference on its own.
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 9,
        trigram_in_pool: 0,
        semantic_in_pool: 8,
      }),
      ["fts", "vector"],
      readiness(null),
    );

    expect(readings[1].state).toBe("silent");
  });

  it("reads hnsw as the meaning-match arm the scenario required", () => {
    // Labs 2 and 3 name that arm `hnsw` in their `expected_techniques`, after
    // the index rather than the retriever. Matching only `vector` and `semantic`
    // left the arm those labs are built on unrequired, so a meaning-match arm
    // that contributed nothing to their pool read as having nothing to say.
    const readings = readChannels(
      response({
        fused_pool: 12,
        fts_in_pool: 5,
        trigram_in_pool: 4,
        semantic_in_pool: 0,
      }),
      ["fts", "pg_trgm", "hnsw", "rrf", "cohere_rerank"],
      readiness(null),
    );

    expect(readings[2].state).toBe("disconnected");
    expect(readings[2].indexName).toBe("product_document_embedding_hnsw_cosine_idx");
  });

  it("names a genuinely missing index rather than blaming the composition", () => {
    const readings = readChannels(
      response({ fused_pool: 12, fts_in_pool: 5, trigram_in_pool: 0, semantic_in_pool: 10 }),
      REQUIRES_TRIGRAM,
      readiness(["product_document_trigram_gin_idx"]),
    );

    expect(readings[1].indexHealthy).toBe(false);
    expect(readings[0].indexHealthy).toBe(true);
  });

  it("says the health check did not run rather than guessing at it", () => {
    // /api/readiness can fail independently of /api/search. A null reading has to
    // stay null: printing "HEALTHY" without having asked would be the surface
    // inventing the one fact the lesson turns on.
    const readings = readChannels(
      response({ fused_pool: 12, fts_in_pool: 5, trigram_in_pool: 0, semantic_in_pool: 10 }),
      REQUIRES_TRIGRAM,
      null,
    );

    expect(readings.every((reading) => reading.indexHealthy === null)).toBe(true);
    // The contribution verdict is independent of it, and still holds.
    expect(readings[1].state).toBe("disconnected");
  });

  it("treats a response with no diagnostics as no contribution reported", () => {
    const withoutDiagnostics: SearchResponse = {
      ...response({}),
      diagnostics: null,
    };
    const readings = readChannels(withoutDiagnostics, REQUIRES_TRIGRAM, readiness(null));

    expect(readings.map((reading) => reading.inPool)).toEqual([0, 0, 0]);
    expect(readings.map((reading) => reading.pool)).toEqual([0, 0, 0]);
  });
});
