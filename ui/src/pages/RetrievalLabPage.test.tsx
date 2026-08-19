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
import { mosaicRetrievalExamples, retrievalExamplesByStage } from "../labMissions";
import { seedProvenance } from "../retrievalSeed";
import { showcaseCatalogPage } from "../showcase";
import type { ProductSummary, RetrievalDiagnostics, SearchResponse } from "../types";
import { RetrievalLabPage } from "./RetrievalLabPage";

vi.mock("../api", () => ({
  api: {
    search: vi.fn(),
  },
}));

// The instrument has its own tests. What matters here is that the page runs the
// right query and hands the response down, so the mock reports what it received.
vi.mock("../components/RetrievalObservatory", () => ({
  RetrievalObservatory: ({
    example,
    loading,
    response,
  }: {
    example?: { id: string };
    loading: boolean;
    response: SearchResponse | null;
  }) => (
    <section aria-label="Retrieval Observatory">
      <p>observatory scenario: {example?.id}</p>
      <p>observatory run: {response ? response.search_event_id : "none"}</p>
      <p>observatory loading: {String(loading)}</p>
    </section>
  ),
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
  searchEventId: string,
  query: string,
  results: ProductSummary[],
): SearchResponse {
  return {
    search_event_id: searchEventId,
    query,
    normalized_query: query,
    applied_filters: {},
    results,
    diagnostics: null,
  };
}

const firstExample = mosaicRetrievalExamples[0];

const primaryResponse = responseFor(
  "retrieval-primary",
  firstExample.query,
  [
    productWithSignals(2, {
      fts: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      trigram: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      semantic: { rank: null, raw_score: null, rrf_contribution: null },
      rrf_score: 0.03279,
      pre_rerank_rank: 1,
      pre_rerank_score: 0.03279,
      rerank_score: 0.72,
      final_rank: 1,
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
  ...primaryResponse,
  search_event_id: "first-retrieval-run",
  results: [
    productWithSignals(2, {
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
  ...primaryResponse,
  search_event_id: "latest-retrieval-run",
  results: [
    productWithSignals(2, {
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

describe("RetrievalLabPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/labs/retrieval");
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockResolvedValue(primaryResponse);
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

  it("carries exactly one way to start a run", () => {
    // Two run controls with different verbs, one live and one replaying a fixture,
    // is how this page ended up teaching that the numbers were not measured.
    render(<RetrievalLabPage />);
    const actions = screen
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());
    expect(actions.filter((label) => /^Run|^Replay/.test(label ?? ""))).toEqual([
      "Run pipeline",
    ]);
  });

  it("puts the scenario choice before the action that runs it", () => {
    // The picker used to sit inside the matrix, below the button that consumed it,
    // so the page read run-then-pick. Both controls are now in the masthead in the
    // order they are used.
    const { container } = render(<RetrievalLabPage />);
    const action = container.querySelector(".retrieval-run-action")!;
    const controls = [...action.querySelectorAll("select, button")];

    expect(controls[0].tagName).toBe("SELECT");
    expect(controls[1].textContent).toContain("Run pipeline");
    // One picker on the page, not one per instrument.
    expect(container.querySelectorAll("select")).toHaveLength(1);
  });

  it("groups the scenarios the way the session runs them", () => {
    // Manifest order interleaves stages and the canonical ids jump 003, 008, 010,
    // 001, 004. Those ids are bound to graded queries in canonical_queries.jsonl,
    // so the fix is the reading order, not a renumbering.
    render(<RetrievalLabPage />);
    const select = screen.getByRole("combobox");
    const groups = [...select.querySelectorAll("optgroup")].map((group) =>
      group.getAttribute("label"),
    );

    expect(groups).toEqual(["Retrieve", "Rank", "Reason", "Advanced"]);
    expect(
      [...select.querySelectorAll("option")].map((option) => option.textContent),
    ).toEqual(
      retrievalExamplesByStage().flatMap((group) =>
        group.examples.map((example) => example.discover_label),
      ),
    );
  });

  it("says what a canonical query id is instead of printing the bare code", () => {
    // "G-003 · Ready" was the first thing a participant read, with nothing to say
    // what G meant.
    const captured = mosaicRetrievalExamples.find(
      (candidate) => candidate.id === seedProvenance.mission_id,
    )!;
    render(<RetrievalLabPage />);

    const banner = document.querySelector(".lab-outcome")!;
    expect(banner.textContent).toContain(
      `Canonical query ${captured.canonical_query_id}`,
    );
  });

  it("judges the checkpoint against the run that is on screen", () => {
    // The banner used to judge live responses only, so on arrival it asserted
    // "The target is absent because the working pg_trgm arm is disconnected from
    // candidate fusion" directly beneath a captured run showing that target at
    // rank 1 with a trigram contribution. The panel refuted its own banner.
    const captured = mosaicRetrievalExamples.find(
      (candidate) => candidate.id === seedProvenance.mission_id,
    )!;
    const edit = captured.participant_edit!;
    render(<RetrievalLabPage />);

    // The capture comes from an intact database, so the checkpoint reads as met.
    expect(screen.getByText(edit.fixed_state)).toBeTruthy();
    expect(screen.queryByText(edit.broken_state)).toBeNull();
  });

  it("has nothing to judge for a scenario with no run yet", () => {
    // The capture describes one scenario. Under any other, the banner reports the
    // ready state rather than borrowing a verdict from a run of something else.
    const other = mosaicRetrievalExamples.find(
      (candidate) => candidate.id !== seedProvenance.mission_id && candidate.stage === "retrieve",
    )!;
    window.history.replaceState({}, "", `/labs/retrieval?example=${other.id}`);
    render(<RetrievalLabPage />);

    expect(screen.getByText("Run to observe")).toBeTruthy();
  });

  it("runs the deep-linked scenario and hands the response to the instrument", async () => {
    const requested = mosaicRetrievalExamples.find(
      (example) => example.id === "semantic-intent-contrast",
    );
    if (!requested) throw new Error("Missing semantic-intent-contrast scenario");
    window.history.replaceState({}, "", "/labs/retrieval?example=semantic-intent-contrast");
    render(<RetrievalLabPage />);

    expect(screen.getByText(`observatory scenario: ${requested.id}`)).toBeTruthy();
    expect(screen.getByText("observatory run: none")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        requested.query,
        requested.filters,
        { limit: 12, rerank: true },
      );
    });
    expect(await screen.findByText("observatory run: retrieval-primary")).toBeTruthy();
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
    expect(screen.getByText("observatory loading: true")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain(
      "Embedding, retrieving, fusing, and reranking.",
    );

    resolveSearch(primaryResponse);

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
    // A failed live call scopes itself to a notice; it does not blank the page.
    expect(screen.getByLabelText("Retrieval Observatory")).toBeTruthy();
  });

  it("ignores a stale response after the participant changes the scenario", async () => {
    let resolveFirst: (response: SearchResponse) => void = () => {};
    vi.mocked(api.search).mockImplementationOnce(
      () => new Promise<SearchResponse>((resolve) => {
        resolveFirst = resolve;
      }),
    );
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "exact-identity" } });
    resolveFirst(primaryResponse);

    await waitFor(() => {
      expect(screen.getByText("observatory scenario: exact-identity")).toBeTruthy();
    });
    // The superseded response never reaches the instrument, and the run state it
    // left behind is cleared rather than left spinning.
    expect(screen.getByText("observatory run: none")).toBeTruthy();
    expect(screen.getByText("observatory loading: false")).toBeTruthy();
  });

  it("preserves factual first and latest run measures after a second pipeline run", async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse);
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("observatory run: first-retrieval-run");
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
