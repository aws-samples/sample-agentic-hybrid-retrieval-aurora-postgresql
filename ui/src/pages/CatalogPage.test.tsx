// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage } from "../showcase";
import type {
  AgentResponse,
  ProductSummary,
  RetrievalDiagnostics,
  SearchResponse,
} from "../types";
import { CatalogPage } from "./CatalogPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    search: vi.fn(),
    agentStream: vi.fn(),
  },
}));

const catalog = showcaseCatalogPage({}, 0, 12);

function rankedProduct(product: ProductSummary, finalRank: number): ProductSummary {
  return {
    ...product,
    signals: {
      fts: { rank: finalRank, raw_score: 0.7, rrf_contribution: 0.01 },
      trigram: { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: finalRank + 1, raw_score: 0.2, rrf_contribution: 0.01 },
      rrf_score: 0.02,
      pre_rerank_rank: finalRank + 1,
      pre_rerank_score: 0.02,
      rerank_score: 0.9 - finalRank / 10,
      final_rank: finalRank,
      score_semantics: "rank_fusion_then_bounded_rerank",
    },
  };
}

const recommendations = catalog.products
  .slice(0, 2)
  .map((product, index) => rankedProduct(product, index + 1));

const searchResponse: SearchResponse = {
  search_event_id: "search-1",
  query: "quiet keyboard",
  normalized_query: "quiet keyboard",
  applied_filters: {},
  results: recommendations,
  diagnostics: {
    strategy: "hybrid_rrf_rerank",
    embedding_model_id: "cohere.embed-v4",
    embedding_dimensions: 1024,
    rerank_model_id: "cohere.rerank-v3-5",
    rerank_status: "applied",
    retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
    candidate_counts: { fused_pool: 18 },
    stage_timings_ms: {},
    total_latency_ms: 42,
  },
};

const agentResponse: AgentResponse = {
  agent_run_id: "agent-1",
  question: "Compare quiet keyboards under $180",
  answer: "Choose the first product based on the cited switch evidence [1].",
  plan: [],
  recommendations,
  citations: [
    {
      number: 1,
      evidence_id: 9001,
      evidence_type: "product_spec",
      product_id: recommendations[0].product_id,
      source_uri: "mosaic://evidence/9001",
      revision: "2026-08-01",
      title: "Acoustic switch specification",
      quote: "Measured for shared-office use.",
    },
  ],
  trace: [
    {
      sequence: 1,
      tool: "search_products",
      detail: "Retrieved a bounded hybrid candidate set.",
      retrieval_run_id: "search-1",
      result_count: 2,
      arguments: { max_price_cents: 18000 },
      outcome: "success",
      latency_ms: 412,
    },
    {
      sequence: 2,
      tool: "get_product_evidence",
      detail: "Resolved supporting product evidence.",
      retrieval_run_id: null,
      result_count: 1,
      arguments: { product_ids: [recommendations[0].product_id] },
      outcome: "success",
      latency_ms: 18,
    },
  ],
};

describe("CatalogPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/catalog");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.search).mockReset();
    vi.mocked(api.agentStream).mockReset();
    vi.mocked(api.catalog).mockResolvedValue(catalog);
    vi.mocked(api.search).mockResolvedValue(searchResponse);
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({
        type: "stage",
        id: "retrieve",
        title: "Retrieve",
        detail: "Searching the hybrid index.",
      });
      onEvent({ type: "answer_start", response: agentResponse });
      onEvent({ type: "answer_delta", delta: agentResponse.answer });
      onEvent({ type: "complete", response: agentResponse });
    });
  });

  afterEach(cleanup);

  function renderPage() {
    return render(
      <CommerceProvider>
        <CatalogPage />
      </CommerceProvider>,
    );
  }

  it("runs hybrid retrieval from the Shop query and renders real rank signals", async () => {
    window.history.replaceState({}, "", "/catalog?q=quiet%20keyboard");
    renderPage();

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        "quiet keyboard",
        {},
        { limit: 12, rerank: true },
      );
    });

    expect(await screen.findByText("Hybrid results")).toBeTruthy();
    expect(screen.getByText(/18 fused candidates/)).toBeTruthy();
    expect(screen.getAllByText("RRF 2").length).toBeGreaterThan(0);
  });

  it("opens Ask Mosaic, renders grounded receipts, and cross-highlights products", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);

    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    expect(
      screen.getByRole("region", { name: "Ask Mosaic composer" }),
    ).toBeTruthy();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    const dialog = screen.getByRole("dialog", { name: "Ask Mosaic" });
    expect(await within(dialog).findByText("Evidence")).toBeTruthy();
    expect(within(dialog).getByText("Acoustic switch specification")).toBeTruthy();
    expect(within(dialog).getByText("search_products")).toBeTruthy();
    expect(within(dialog).getByText(/max_price_cents/)).toBeTruthy();
    expect(screen.getByText("Ask Mosaic shortlist")).toBeTruthy();

    const shortlistItem = within(dialog)
      .getByText(recommendations[0].model)
      .closest("li");
    expect(shortlistItem).not.toBeNull();
    fireEvent.mouseEnter(shortlistItem!);
    expect(
      document.querySelector(".catalog-product-card.assist-highlighted"),
    ).not.toBeNull();
    fireEvent.mouseLeave(shortlistItem!);
    expect(
      document.querySelector(".catalog-product-card.assist-highlighted"),
    ).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Compare top two" }));
    await waitFor(() => expect(api.agentStream).toHaveBeenCalledTimes(2));
  });

  it("closes the sidecar and can restore the underlying Shop results", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    expect(
      screen.getByRole("region", { name: "Ask Mosaic composer" }),
    ).toBeTruthy();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Ask Mosaic shortlist");

    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Ask Mosaic" }))
        .getByRole("button", { name: "Close Ask Mosaic" }),
    );
    expect(screen.queryByRole("dialog", { name: "Ask Mosaic" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clear shortlist" }));
    expect(screen.queryByText("Ask Mosaic shortlist")).toBeNull();
    expect(screen.getByText(/of 120 products/)).toBeTruthy();
  });
});
