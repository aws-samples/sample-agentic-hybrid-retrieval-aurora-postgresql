import { describe, expect, it } from "vitest";
import {
  agentLabOutcome,
  liveRetrievalOutcome,
  retrievalLabOutcome,
  runMatchesMissionGates,
} from "./labOutcome";
import {
  coreMosaicLabs,
  type MosaicLabMission,
} from "./labMissions";
import type {
  AgentResponse,
  ProductSummary,
  ReadinessResponse,
  RetrievalDiagnostics,
  SearchResponse,
} from "./types";

/** Every required object present and every count at its shipped value. */
const healthyReadiness: ReadinessResponse = {
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
    evidence_product_count: 500_000,
    missing_retrieval_indexes: null,
    missing_retrieval_functions: null,
    exact_neighbor_ground_truth: "seeded",
    exact_neighbor_ground_truth_detail: null,
  },
  configured_models: {
    embedding: "us.cohere.embed-v4:0",
    rerank: "cohere.rerank-v3-5:0",
    agent: "agent-model",
    synthesis: "synthesis-model",
  },
  bedrock_credentials: { ready: true },
};

const testFusionK = 7;

function product(
  productId: number,
  contribution: (rank: number) => number,
): ProductSummary {
  return {
    product_id: productId,
    sku: `SKU-${productId}`,
    title: "Product",
    short_description: "Description",
    domain: "home_office",
    category_key: "chairs",
    category_path: "Home office / Chairs",
    brand: "Mosaic",
    model: `M-${productId}`,
    price_cents: 69900,
    list_price_cents: 69900,
    currency: "USD",
    rating: 4.8,
    review_count: 20,
    availability: "in_stock",
    inventory_count: 10,
    attributes: { seat_depth_adjustable: true },
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: true,
    is_retrieval_anchor: true,
    image_url: null,
    image_source: null,
    sources: [],
    signals: {
      fts: { rank: 1, raw_score: 0.5, rrf_contribution: contribution(1) },
      trigram: { rank: 2, raw_score: 0.4, rrf_contribution: contribution(2) },
      semantic: { rank: 3, raw_score: 0.3, rrf_contribution: contribution(3) },
      rrf_score: contribution(1) + contribution(2) + contribution(3),
      pre_rerank_rank: 1,
      pre_rerank_score: 0.1,
      rerank_score: 0.9,
      final_rank: 1,
      score_semantics: "test",
    },
  };
}

function response(result: ProductSummary, rrfK = testFusionK): SearchResponse {
  return {
    search_event_id: "run-1",
    query: "query",
    normalized_query: "query",
    applied_filters: {},
    results: [result],
    diagnostics: {
      strategy: "rrf",
      embedding_model_id: "embed",
      embedding_dimensions: 1024,
      rerank_model_id: "rerank",
      rerank_status: "applied",
      retrieval_profile: {
        rrf_k: rrfK,
      } as RetrievalDiagnostics["retrieval_profile"],
      candidate_counts: { trigram_in_pool: 1 },
      stage_timings_ms: {},
      total_latency_ms: 1,
    },
  };
}

describe("lab outcome diagnostics", () => {
  it("distinguishes collapsed and repaired RRF arithmetic", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "rank")!;
    const broken = product(370002, () => 1 / (testFusionK + 1));
    const fixed = product(370002, (rank) => 1 / (testFusionK + rank));

    expect(retrievalLabOutcome(mission, response(broken)).tone).toBe("broken");
    expect(retrievalLabOutcome(mission, response(fixed)).tone).toBe("fixed");
  });

  it("requires agent tool receipts and evidence citations", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "reason")!;
    const recommendation = product(
      370001,
      (rank) => 1 / (testFusionK + rank),
    );
    const agent = {
      agent_run_id: "agent-1",
      question: mission.query,
      answer: "Answer",
      plan: [],
      recommendations: [recommendation, { ...recommendation, product_id: 429001 }],
      citations: [370001, 429001].map((productId, index) => ({
        number: index + 1,
        evidence_id: 9001 + index,
        evidence_type: "product_spec",
        product_id: productId,
        source_uri: `mosaic://evidence/${9001 + index}`,
        revision: "1",
        title: "Evidence",
        quote: "Support",
      })),
      trace: ["search_products", "compare_products", "get_product_evidence"].map(
        (tool, index) => ({
          sequence: index + 1,
          tool,
          detail: "ok",
          retrieval_run_id: null,
          result_count: 1,
          arguments: {},
          outcome: "success" as const,
          latency_ms: 12,
        }),
      ),
    } satisfies AgentResponse;

    expect(agentLabOutcome(mission, agent, "").tone).toBe("fixed");
    expect(agentLabOutcome(mission, { ...agent, citations: [] }, "").tone).toBe("broken");
  });

  it("does not claim a checkpoint passed before a production response exists", () => {
    const mission = coreMosaicLabs[0] as MosaicLabMission;
    const outcome = retrievalLabOutcome(mission, null);
    expect(outcome.tone).toBe("ready");
    expect(outcome.label).toBe("Ready to run");
    expect(outcome.label).not.toContain("Canonical query");
  });

  it("uses participant-facing stage verdicts without exposing query ids", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
    const eligibleTarget = {
      ...product(
        mission.target_product_ids[0],
        (rank) => 1 / (testFusionK + rank),
      ),
      domain: mission.filters.domain ?? "home_office",
      price_cents: Math.min(
        69900,
        mission.filters.max_price_cents ?? 69900,
      ),
      availability: "in_stock" as const,
      attributes: {
        seat_depth_adjustable: true,
        ...mission.filters.attributes,
      },
    };
    const outcome = retrievalLabOutcome(
      mission,
      response(eligibleTarget),
    );

    expect(outcome.label).toBe("Repair verified");
    expect(outcome.title).toBe("Fuzzy retrieval is contributing");
    expect(outcome.label).not.toContain("Canonical query");
  });

  it("keeps edited live queries neutral", () => {
    const outcome = liveRetrievalOutcome(
      response(product(2, (rank) => 1 / (testFusionK + rank))),
    );

    expect(outcome.label).toBe("Live run complete");
    expect(outcome.title).toBe("1 ranked result");
  });

  it("labels a carried Shop run without claiming the scenario's verdict", () => {
    // The run came from Shop, so it ran under Shop's gates. Printing "Live run
    // complete" over it said nothing about where it came from, and printing the
    // lab verdict over it would grade the scenario against someone else's request.
    const outcome = liveRetrievalOutcome(
      response(product(2, (rank) => 1 / (testFusionK + rank))),
      true,
    );

    expect(outcome.label).toBe("Shop run loaded");
    expect(outcome.detail).toContain("scenario's own filters");
  });

  it("keeps the outside-the-checkpoint sentence for a query of the participant's own", () => {
    // Words the scenario never asked. Whether its gates happen to match is then
    // beside the point: the run is off the checkpoint, not measuring it under
    // someone else's filters.
    const ran = response(product(2, (rank) => 1 / (testFusionK + rank)));

    for (const gatesMatch of [false, true]) {
      const outcome = liveRetrievalOutcome(ran, false, { queryMatches: false, gatesMatch });

      expect(outcome.detail).toContain("This query is outside the selected checkpoint.");
      expect(outcome.detail).not.toContain("Shop's gates");
    }
  });

  it("says the gates diverged, not the query, on a re-run of a carried request", () => {
    // `Run pipeline` after a carried arrival re-runs the carried request, so the
    // query *is* the scenario's and only the gates are Shop's. "This query is
    // outside the selected checkpoint" was simply false of that run, and it sent
    // the participant to change the one half that had not diverged.
    const outcome = liveRetrievalOutcome(
      response(product(2, (rank) => 1 / (testFusionK + rank))),
      false,
      { queryMatches: true, gatesMatch: false },
    );

    expect(outcome.label).toBe("Live run complete");
    expect(outcome.detail).toBe(
      "This run used Shop's gates, so the lab verdict does not apply. Select the scenario and run it, or run the completion proof in Prove, to judge the repair against the scenario's own gates.",
    );
    expect(outcome.detail).not.toContain("outside the selected checkpoint");
  });

  it("only applies a lab verdict when the run used the scenario's own gates", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
    const ran = response(product(2, (rank) => 1 / (testFusionK + rank)));

    // The mission constrains domain, price and stock. A run that applied none of
    // them retrieved a wider pool than the scenario describes.
    expect(runMatchesMissionGates(mission, ran)).toBe(false);
    expect(
      runMatchesMissionGates(mission, {
        ...ran,
        applied_filters: { ...mission.filters },
      }),
    ).toBe(true);
  });

  it("ignores the attribute map when comparing gates", () => {
    // `attributes` is not forwardable, so Shop can never carry it and a run that
    // omits it is not thereby a different request.
    const mission = coreMosaicLabs.find((item) => item.stage === "rank")!;
    const ran = response(product(370002, (rank) => 1 / (testFusionK + rank)));

    expect(
      runMatchesMissionGates(mission, {
        ...ran,
        applied_filters: { domain: "home_office", in_stock_only: true },
      }),
    ).toBe(true);
  });

  it("treats a false gate and an absent one as the same request", () => {
    // `SearchFilters.as_sql_json` drops false booleans before the service logs
    // or echoes them, because a missing key and `in_stock_only: false` mean the
    // same thing to the SQL. A scenario that spells the false out could then
    // never match the echo of its own run, in either direction.
    const mission = {
      ...coreMosaicLabs[0],
      filters: { domain: "consumer_electronics", in_stock_only: false },
    } satisfies MosaicLabMission;
    const ran = response(product(2, (rank) => 1 / (testFusionK + rank)));

    expect(
      runMatchesMissionGates(mission, {
        ...ran,
        applied_filters: { domain: "consumer_electronics" },
      }),
    ).toBe(true);
    expect(
      runMatchesMissionGates(
        { ...mission, filters: { domain: "consumer_electronics" } },
        { ...ran, applied_filters: { domain: "consumer_electronics", in_stock_only: false } },
      ),
    ).toBe(true);
    // A true gate is still a gate: only the falsy pair collapses.
    expect(
      runMatchesMissionGates(mission, {
        ...ran,
        applied_filters: { domain: "consumer_electronics", in_stock_only: true },
      }),
    ).toBe(false);
  });

  it("blames the environment, not the lab, when the database is not ready", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
    const outcome = retrievalLabOutcome(
      mission,
      response(product(2, (rank) => 1 / (testFusionK + rank))),
      {
        ...healthyReadiness,
        status: "blocked",
        database_ready: false,
      },
    );

    expect(outcome.tone).toBe("unhealthy");
    expect(outcome.title).toBe(
      "This is an environment problem, not the lab's fault",
    );
    expect(outcome.detail).toContain("not ready");
  });

  it("names the missing index for the arm this lab needs", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
    const outcome = retrievalLabOutcome(
      mission,
      response(product(2, (rank) => 1 / (testFusionK + rank))),
      {
        ...healthyReadiness,
        database: {
          ...healthyReadiness.database,
          missing_retrieval_indexes: ["product_document_trigram_gin_idx"],
        },
      },
    );

    expect(outcome.tone).toBe("unhealthy");
    expect(outcome.detail).toContain("product_document_trigram_gin_idx");
  });

  it("names the HNSW index for a lab whose techniques call it hnsw", () => {
    // Labs 2 and 3 declare `hnsw` rather than `vector` or `semantic`, so the arm
    // map matched nothing and the one index those labs cannot run without was
    // never health-checked: a dropped HNSW index read as the participant's own
    // fusion defect.
    const mission = coreMosaicLabs.find((item) => item.stage === "rank")!;
    expect(mission.expected_techniques).toContain("hnsw");

    const outcome = retrievalLabOutcome(
      mission,
      response(product(370002, (rank) => 1 / (testFusionK + rank))),
      {
        ...healthyReadiness,
        database: {
          ...healthyReadiness.database,
          missing_retrieval_indexes: ["product_document_embedding_hnsw_cosine_idx"],
        },
      },
    );

    expect(outcome.tone).toBe("unhealthy");
    expect(outcome.detail).toContain("product_document_embedding_hnsw_cosine_idx");
  });

  it("leaves an index this lab does not use out of its verdict", () => {
    // Lab 1 requires the close-spelling arm. A full-text index this scenario
    // never asks for is not what stops its repair from being observable, and
    // reporting it as one sends the participant to the wrong place.
    const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
    const outcome = retrievalLabOutcome(
      mission,
      response(product(2, (rank) => 1 / (testFusionK + rank))),
      {
        ...healthyReadiness,
        database: {
          ...healthyReadiness.database,
          missing_retrieval_indexes: ["product_document_fts_gin_idx"],
        },
      },
    );

    expect(outcome.tone).not.toBe("unhealthy");
  });

  it("keeps an expected lab defect broken while the environment is healthy", () => {
    const mission = coreMosaicLabs.find((item) => item.stage === "rank")!;
    const broken = product(370002, () => 1 / (testFusionK + 1));

    expect(retrievalLabOutcome(mission, response(broken), healthyReadiness).tone)
      .toBe("broken");
  });
});
