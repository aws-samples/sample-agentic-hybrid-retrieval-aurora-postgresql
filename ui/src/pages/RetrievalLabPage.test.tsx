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
import { mosaicRetrievalExamples } from "../labMissions";
import { showcaseCatalogPage } from "../showcase";
import type { ProductSummary, RetrievalDiagnostics, SearchResponse } from "../types";
import { RetrievalLabPage } from "./RetrievalLabPage";

vi.mock("../api", () => ({
  api: {
    search: vi.fn(),
  },
}));
vi.mock("../components/RetrievalObservatory", () => ({
  RetrievalObservatory: () => <section aria-label="Retrieval Observatory" />,
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
  "EchoBud S2",
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

const firstComparisonDiagnostics = {
  strategy: "hybrid",
  embedding_model_id: "us.cohere.embed-v4:0",
  embedding_dimensions: 1024,
  rerank_model_id: "cohere.rerank-v3-5:0",
  rerank_status: "applied" as const,
  retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
  candidate_counts: { trigram_in_pool: 0 },
  stage_timings_ms: {},
  total_latency_ms: 100,
} satisfies NonNullable<SearchResponse["diagnostics"]>;

const firstComparisonResponse = {
  ...exactIdentityResponse,
  search_event_id: "first-retrieval-run",
  results: [
    productWithSignals(17001, {
      fts: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      trigram: { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: null, raw_score: null, rrf_contribution: null },
      rrf_score: 0.01639,
      pre_rerank_rank: 7,
      pre_rerank_score: 0.01639,
      rerank_score: 0.35,
      final_rank: 6,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
  ],
  diagnostics: firstComparisonDiagnostics,
} satisfies SearchResponse;

const latestComparisonResponse = {
  ...exactIdentityResponse,
  search_event_id: "latest-retrieval-run",
  results: [
    productWithSignals(17001, {
      fts: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      trigram: { rank: 1, raw_score: 0.87, rrf_contribution: 0.01639 },
      semantic: { rank: null, raw_score: null, rrf_contribution: null },
      rrf_score: 0.03279,
      pre_rerank_rank: 1,
      pre_rerank_score: 0.03279,
      rerank_score: 0.81,
      final_rank: 1,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
  ],
  diagnostics: {
    ...firstComparisonResponse.diagnostics,
    candidate_counts: { trigram_in_pool: 4 },
  },
} satisfies SearchResponse;

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

  it("is reachable from the other Labs views and marks itself current", () => {
    // A documented participant surface that carried no Labs navigation, so the
    // only ways in were a product-page link and a lab-mission deep link.
    render(<RetrievalLabPage />);

    const strip = screen.getByRole("navigation", { name: "Mosaic retrieval views" });
    expect(screen.getByRole("heading", { name: "Retrieval Observatory" })).toBeTruthy();
    // Internal routes only; the strip also carries an outbound GitHub link.
    expect(
      within(strip)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
        .filter((href) => href?.startsWith("/")),
    ).toEqual(["/labs/retrieval", "/mosaic-labs/hnsw", "/mosaic-labs/studio"]);
    expect(
      within(strip).getByRole("link", { name: "Retrieval Observatory" }).getAttribute("aria-current"),
    ).toBe("page");
  });

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

  it("shows an immediate running state while the retrieval request is in flight", async () => {
    let resolveSearch: (response: SearchResponse) => void = () => {};
    vi.mocked(api.search).mockImplementationOnce(
      () => new Promise<SearchResponse>((resolve) => {
        resolveSearch = resolve;
      }),
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    const action = screen.getByRole("button", { name: "Running pipeline" });
    expect((action as HTMLButtonElement).disabled).toBe(true);
    expect(action.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("status").textContent).toContain(
      "Embedding, retrieving, fusing, and reranking.",
    );

    resolveSearch(exactIdentityResponse);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Run pipeline" })).toBeTruthy();
    });
  });

  it("shows a recoverable API failure beside the action", async () => {
    vi.mocked(api.search).mockRejectedValueOnce(
      new Error("Amazon Bedrock credentials are unavailable (ExpiredTokenException)."),
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(
      "The Mosaic API AWS session has expired. Refresh it, restart the API, then retry.",
    );
    expect(screen.getByRole("button", { name: "Retry pipeline" })).toBeTruthy();
  });

  it("ignores a stale response after the participant changes the checkpoint", async () => {
    let resolveFirst: (response: SearchResponse) => void = () => {};
    vi.mocked(api.search).mockImplementationOnce(
      () => new Promise<SearchResponse>((resolve) => {
        resolveFirst = resolve;
      }),
    );

    window.history.replaceState(
      {},
      "",
      "/labs/retrieval?example=exact-identity",
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "1" } });
    resolveFirst(exactIdentityResponse);

    await waitFor(() => {
      expect(screen.queryByText("Where does this target enter?")).toBeNull();
    });
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("1");
  });

  it("preserves factual first and latest run measures after a second pipeline run", async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse);
    window.history.replaceState({}, "", "/labs/retrieval?example=exact-identity");
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("Target returns at final rank #6.");
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("First run and latest run")).toBeTruthy();
    const firstRun = screen.getByLabelText("First run metrics");
    const latestRun = screen.getByLabelText("Latest run metrics");
    expect(within(firstRun).getByText("#7")).toBeTruthy();
    expect(within(firstRun).getByText("#6")).toBeTruthy();
    expect(within(firstRun).getByText("0")).toBeTruthy();
    expect(within(latestRun).getAllByText("#1")).toHaveLength(2);
    expect(within(latestRun).getByText("4")).toBeTruthy();
  });
});
