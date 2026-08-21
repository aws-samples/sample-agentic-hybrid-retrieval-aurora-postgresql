import { describe, expect, it } from "vitest";
import {
  agentLabOutcome,
  liveRetrievalOutcome,
  retrievalLabOutcome,
} from "./labOutcome";
import {
  coreMosaicLabs,
  type MosaicLabMission,
} from "./labMissions";
import type {
  AgentResponse,
  ProductSummary,
  RetrievalDiagnostics,
  SearchResponse,
} from "./types";

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
});
