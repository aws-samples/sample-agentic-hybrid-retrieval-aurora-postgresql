// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { mosaicRetrievalExamples } from "../labMissions";
import { showcaseCatalogPage } from "../showcase";
import type { ProductSummary, SearchResponse } from "../types";
import { RetrievalLabPage } from "./RetrievalLabPage";

vi.mock("../api", () => ({
  api: {
    search: vi.fn(),
  },
}));

const catalog = showcaseCatalogPage({}, 0, 120);

function productWithSignals(
  productId: number,
  signals: NonNullable<ProductSummary["signals"]>,
): ProductSummary {
  const product = catalog.products.find((candidate) => candidate.product_id === productId);
  if (!product) throw new Error(`Missing showcase product ${productId}`);
  return { ...product, signals };
}

function responseFor(
  query: string,
  results: ProductSummary[],
): SearchResponse {
  return {
    search_event_id: "retrieval-contrast",
    query,
    normalized_query: query,
    applied_filters: {},
    results,
    diagnostics: null,
  };
}

const exactIdentityResponse = responseFor(
  "CO-TRUEW-0017001 charging case",
  [
    productWithSignals(17001, {
      fts: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      trigram: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      semantic: { rank: null, raw_score: null, rrf_contribution: null },
      rrf_score: 0.03279,
      pre_rerank_rank: 1,
      pre_rerank_score: 0.03279,
      rerank_score: 0.72,
      final_rank: 2,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
  ],
);

const semanticIntentResponse = responseFor(
  "noise cancelling headphones for a long flight under $200 with at least 40 hours of battery",
  [
    productWithSignals(3, {
      fts: { rank: null, raw_score: null, rrf_contribution: null },
      trigram: { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: 1, raw_score: 0.82, rrf_contribution: 0.01639 },
      rrf_score: 0.01639,
      pre_rerank_rank: 5,
      pre_rerank_score: 0.01639,
      rerank_score: 0.77,
      final_rank: 3,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
  ],
);

describe("RetrievalLabPage retriever contrasts", () => {
  beforeEach(() => {
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockImplementation((query) => {
      if (query === exactIdentityResponse.query) {
        return Promise.resolve(exactIdentityResponse);
      }
      if (query === semanticIntentResponse.query) {
        return Promise.resolve(semanticIntentResponse);
      }
      throw new Error(`Unexpected contrast query: ${query}`);
    });
  });

  afterEach(cleanup);

  it("makes the FTS identity win and vector miss observable from live ranks", async () => {
    window.history.replaceState(
      {},
      "",
      "/labs/retrieval?example=exact-identity",
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        exactIdentityResponse.query,
        { domain: "consumer_electronics" },
        { limit: 12, rerank: true },
      );
    });
    expect(await screen.findByText("Where does this target enter?")).toBeTruthy();
    expect(screen.getByText("Target enters the lexical candidate list at #1.")).toBeTruthy();
    expect(screen.getByText("Break: target absent from the vector candidate list.")).toBeTruthy();
    expect(screen.getByText("Target returns at final rank #2.")).toBeTruthy();
  });

  it("makes the semantic win and lexical miss observable from live ranks", async () => {
    const semanticExample = mosaicRetrievalExamples.find(
      (example) => example.id === "semantic-intent-contrast",
    );
    if (!semanticExample) throw new Error("Missing semantic-intent-contrast example");

    window.history.replaceState(
      {},
      "",
      "/labs/retrieval?example=semantic-intent-contrast",
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        semanticExample.query,
        semanticExample.filters,
        { limit: 12, rerank: true },
      );
    });
    expect(await screen.findByText("Where does this target enter?")).toBeTruthy();
    expect(screen.getByText("Break: target absent from the lexical candidate list.")).toBeTruthy();
    expect(screen.getByText("Target enters the HNSW candidate list at #1.")).toBeTruthy();
    expect(screen.getByText("Target returns at final rank #3.")).toBeTruthy();
  });
});
