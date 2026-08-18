// @vitest-environment jsdom

import {
  act,
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
import { stageDwellMs } from "../components/AskMosaic";
import { catalogGhostQueries } from "../components/CatalogSearchComposer";
import { showcaseCatalogPage } from "../showcase";
import type {
  AgentResponse,
  CatalogPage as CatalogPageResponse,
  CatalogSuggestion,
  ProductSummary,
  RetrievalDiagnostics,
  RetrievalExample,
  SearchResponse,
} from "../types";
import { CatalogPage } from "./CatalogPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    suggestions: vi.fn(),
    search: vi.fn(),
    agentStream: vi.fn(),
    examples: vi.fn(),
  },
}));

/**
 * Shaped like `/api/retrieval/examples`, which serves `demo_queries.jsonl`
 * deduplicated in file order. The second consumer_electronics row is here to
 * prove the panel takes the first query per domain rather than the first three.
 */
const examples: RetrievalExample[] = [
  {
    query_id: "D-001",
    domain: "consumer_electronics",
    query: "Find wireless noise-cancelling over-ear headphones under $200",
    expected_techniques: ["lexical", "semantic"],
    variant: 1,
  },
  {
    query_id: "D-002",
    domain: "consumer_electronics",
    query: "Bluetooth earbuds with a charging case",
    expected_techniques: ["lexical"],
    variant: 1,
  },
  {
    query_id: "D-006",
    domain: "running_fitness",
    query: "Carbon-plated marathon shoes under $220",
    expected_techniques: ["semantic"],
    variant: 1,
  },
  {
    query_id: "D-011",
    domain: "home_office",
    query: "Ergonomic mesh chair with adjustable lumbar support under $500",
    expected_techniques: ["semantic"],
    variant: 1,
  },
];

const catalog = {
  ...showcaseCatalogPage({}, 0, 12),
  total: 200,
};
const suggestions: CatalogSuggestion[] = [
  {
    kind: "product",
    label: "Mosaic Auraluxe H9 Premium Wireless Headphones",
    query: "Mosaic Auraluxe H9 Premium Wireless Headphones",
    product_id: 1,
    domain: "consumer_electronics",
    brand: "Mosaic",
    category_key: "over-ear-headphones",
    category_path: "Audio > Over-Ear Headphones",
  },
  {
    kind: "brand",
    label: "Auraluxe",
    query: "Auraluxe",
    product_id: null,
    domain: null,
    brand: "Auraluxe",
    category_key: null,
    category_path: null,
  },
];

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
  plan: [
    {
      query: "quiet mechanical keyboard for shared offices",
      filters: { max_price_cents: 18000, in_stock_only: true },
      purpose: "Retrieve products for: quiet mechanical keyboard for shared offices",
    },
  ],
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
    {
      number: 2,
      evidence_id: 9002,
      evidence_type: "product_spec",
      product_id: recommendations[1].product_id,
      source_uri: "mosaic://evidence/9002",
      revision: "2026-08-01",
      title: "Alternative keyboard specification",
      quote: "A lower-cost option with fewer mechanical controls.",
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
      tool: "compare_products",
      detail: "Compared the returned shortlist.",
      retrieval_run_id: "search-1",
      result_count: 2,
      arguments: { product_ids: recommendations.map((product) => product.product_id) },
      outcome: "success",
      latency_ms: 8,
    },
    {
      sequence: 3,
      tool: "get_product_evidence",
      detail: "Resolved supporting product evidence.",
      retrieval_run_id: null,
      result_count: 2,
      arguments: { product_ids: recommendations.map((product) => product.product_id) },
      outcome: "success",
      latency_ms: 18,
    },
    {
      sequence: 4,
      tool: "synthesize_cited_answer",
      detail: "Synthesized the grounded recommendation.",
      retrieval_run_id: null,
      result_count: 2,
      arguments: { citation_count: 2 },
      outcome: "success",
      latency_ms: 220,
    },
  ],
};

describe("CatalogPage", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    window.history.replaceState({}, "", "/catalog");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.suggestions).mockReset();
    vi.mocked(api.search).mockReset();
    vi.mocked(api.agentStream).mockReset();
    vi.mocked(api.examples).mockReset();
    vi.mocked(api.catalog).mockResolvedValue(catalog);
    vi.mocked(api.suggestions).mockResolvedValue({
      query: "aura",
      suggestions,
    });
    vi.mocked(api.search).mockResolvedValue(searchResponse);
    vi.mocked(api.examples).mockResolvedValue(examples);
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

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("reveals retrieved candidates on the stage that is still running", async () => {
    // The panel built its stage content from the finished response only, so
    // every card stayed empty for the length of the run: the in-progress stage
    // rendered an expanded chevron over a blank box, and everything appeared at
    // once at the end. `partial` carries retrieval that has already returned.
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({
        type: "stage",
        id: "retrieve",
        title: "Retrieve",
        detail: "Searching the hybrid index.",
      });
      onEvent({
        type: "partial",
        partial: {
          plan: agentResponse.plan,
          candidates: agentResponse.recommendations,
          trace: agentResponse.trace,
        },
      });
      await held;
      onEvent({ type: "complete", response: agentResponse });
    });

    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const timeline = within(dialog).getByLabelText("Evidence timeline");
    await waitFor(() =>
      expect(within(dialog).queryByText("Candidates retrieved")).not.toBeNull());

    // By class, not by role: an open card puts its candidate rows inside the
    // timeline, so `getAllByRole("button")` no longer means "the four stages".
    const stageCards = () => [
      ...timeline.querySelectorAll<HTMLButtonElement>(".ask-mosaic-stage-summary"),
    ];
    const running = stageCards();
    expect(running).toHaveLength(4);
    // Retrieve is the stage in progress, and it is showing real rows.
    expect(running[1].getAttribute("aria-expanded")).toBe("true");
    const revealed = dialog.querySelector<HTMLElement>(".ask-mosaic-shortlist");
    expect(
      within(revealed!).getByRole("button", {
        name: new RegExp(recommendations[0].model),
      }),
    ).toBeTruthy();
    // Interpret finished mid-run, so it holds its result open for a beat and
    // then folds itself away. Instant folding meant nothing was ever legible.
    expect(running[0].getAttribute("aria-expanded")).toBe("true");
    expect(within(dialog).getByText("What I understood")).toBeTruthy();
    await waitFor(
      () => expect(stageCards()[0].getAttribute("aria-expanded")).toBe("false"),
      { timeout: stageDwellMs + 2000 },
    );
    // The card collapses its height first and unmounts the content after, so
    // this is reached once the exit finishes rather than in the same frame.
    await waitFor(() =>
      expect(within(dialog).queryByText("What I understood")).toBeNull());
    // Compare and Cite have not run. Candidate rows exist, so their panels
    // could be built - a pending stage must still disclose nothing.
    expect(running[2].hasAttribute("aria-expanded")).toBe(false);
    expect(running[2].disabled).toBe(true);
    expect(within(dialog).queryByText("Compared on catalog data")).toBeNull();

    release();
    await waitFor(() =>
      expect(within(dialog).queryByText("Final recommendation")).not.toBeNull());
    // Finishing folds the retrieve card back up, leaving the answer open.
    expect(stageCards().map((card) => card.getAttribute("aria-expanded")))
      .toEqual(["false", "false", "false", "true"]);
  });

  it("ends the answer in the store, with the cited products buyable", async () => {
    // The answer used to finish as prose. These are the same products the prose
    // names - `recommendations` is the cited set - and the bag button is the
    // cart the rest of the store uses, not a decorative one.
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    await within(dialog).findByText("Final recommendation");
    const picks = within(dialog).getByLabelText("Recommended products");
    expect(
      [...picks.querySelectorAll(".ask-mosaic-pick-open strong")]
        .map((name) => name.textContent),
    ).toEqual(
      recommendations
        .slice(0, 3)
        .map((product) => `${product.brand} ${product.model}`),
    );

    const add = within(picks).getAllByRole("button", { name: /Add to bag/ })[0];
    fireEvent.click(add);
    expect(within(picks).getAllByRole("button", { name: /In bag \(1\)/ })).toHaveLength(1);
  });

  function renderPage() {
    return render(
      <CommerceProvider>
        <CatalogPage />
      </CommerceProvider>,
    );
  }

  it("distinguishes curated browsing from full-catalog retrieval", async () => {
    renderPage();

    expect(
      screen.getByText(
        "Search naturally, browse with intention, or ask Mosaic for help finding what fits.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/photographed in one light/i)).toBeNull();
  });

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
    expect(screen.getAllByText("RRF #2").length).toBeGreaterThan(0);
    expect(api.catalog).not.toHaveBeenCalled();
  });

  it("offers keyboard-selectable catalog matches before hybrid retrieval", async () => {
    renderPage();
    const input = screen.getByRole("combobox", { name: "Product search" });

    fireEvent.change(input, { target: { value: "a" } });
    await new Promise((resolve) => window.setTimeout(resolve, 220));
    expect(api.suggestions).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "aura" } });
    const listbox = await screen.findByRole("listbox");
    await waitFor(() => {
      expect(api.suggestions).toHaveBeenCalledWith(
        "aura",
        expect.any(AbortSignal),
      );
    });
    expect(
      within(listbox).getByRole("option", {
        name: /Mosaic Auraluxe H9 Premium Wireless Headphones/,
      }),
    ).toBeTruthy();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        suggestions[0].query,
        {},
        { limit: 12, rerank: true },
      );
    });
  });

  it("surfaces a validated catalog query after the empty field rests", async () => {
    renderPage();
    const input = screen.getByRole("combobox", { name: "Product search" });

    expect(document.querySelector(".catalog-idle-suggestion")).toBeNull();
    await waitFor(
      () => {
        expect(
          document.querySelector(".catalog-idle-suggestion")?.textContent,
        ).toBe(catalogGhostQueries[0]);
      },
      { timeout: 1800 },
    );

    fireEvent.submit(input.closest("form")!);
    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        catalogGhostQueries[0],
        {},
        { limit: 12, rerank: true },
      );
    });
  });

  it("shows a catalog failure instead of substituting showcase products", async () => {
    vi.mocked(api.catalog).mockRejectedValue(new Error("Aurora catalog is unavailable"));
    renderPage();

    expect(
      await screen.findByText("Aurora catalog is unavailable"),
    ).toBeTruthy();
    expect(document.querySelectorAll("[data-product-id]")).toHaveLength(0);
  });

  it("reserves the product grid while the initial catalog request is pending", async () => {
    let releaseCatalog: (value: CatalogPageResponse) => void = () => {};
    vi.mocked(api.catalog).mockImplementation(
      () =>
        new Promise<CatalogPageResponse>((resolve) => {
          releaseCatalog = resolve;
        }),
    );

    renderPage();

    const loading = screen.getByRole("status", { name: "Loading products" });
    expect(loading.querySelectorAll(".catalog-skeleton-card")).toHaveLength(8);
    expect(loading.querySelector(".spin")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Show more product domains" }),
    ).toBeTruthy();

    await act(async () => releaseCatalog(catalog));
  });

  it("synchronizes the domain control after a manual horizontal scroll", () => {
    renderPage();

    const domains = screen.getByRole("navigation", { name: "Product domains" });
    Object.defineProperties(domains, {
      clientWidth: { configurable: true, value: 200 },
      scrollWidth: { configurable: true, value: 500 },
      scrollLeft: { configurable: true, writable: true, value: 300 },
    });
    fireEvent.scroll(domains);

    expect(
      screen.getByRole("button", { name: "Show earlier product domains" }),
    ).toBeTruthy();
  });

  it("moves one shared indicator between product domains", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);

    const allProducts = screen.getByRole("button", { name: "All products" });
    const running = screen.getByRole("button", { name: "Running & fitness" });
    expect(allProducts.querySelector(".shop-domain-indicator")).toBeTruthy();
    expect(document.querySelectorAll(".shop-domain-indicator")).toHaveLength(1);

    fireEvent.click(running);

    await waitFor(() => {
      expect(window.location.search).toContain("domain=running_fitness");
      expect(running.querySelector(".shop-domain-indicator")).toBeTruthy();
    });
    expect(allProducts.querySelector(".shop-domain-indicator")).toBeNull();
    expect(document.querySelectorAll(".shop-domain-indicator")).toHaveLength(1);
  });

  it("shows the inspectable hybrid pipeline while Shop retrieval is pending", async () => {
    let releaseSearch: (value: SearchResponse) => void = () => {};
    vi.mocked(api.search).mockImplementation(
      () =>
        new Promise<SearchResponse>((resolve) => {
          releaseSearch = resolve;
        }),
    );
    window.history.replaceState({}, "", "/catalog?q=ergonomic%20mesh%20chair");
    renderPage();

    const trace = await screen.findByLabelText(
      "Hybrid retrieval request scope",
    );
    expect(
      within(trace).getByText(
        "This request runs the same production path. Individual stages are not streamed, so Mosaic does not invent their completion order.",
      ),
    ).toBeTruthy();
    expect(within(trace).getByText("Cohere Embed v4")).toBeTruthy();
    expect(within(trace).getByText("FTS")).toBeTruthy();
    expect(within(trace).getByText("pg_trgm")).toBeTruthy();
    expect(within(trace).getByText("HNSW")).toBeTruthy();
    expect(within(trace).getByText("SQL eligibility")).toBeTruthy();
    expect(within(trace).getByText("RRF")).toBeTruthy();
    expect(within(trace).getByText("Cohere Rerank")).toBeTruthy();
    expect(
      screen.getByRole("status", { name: "Loading products" })
        .querySelectorAll(".catalog-skeleton-card"),
    ).toHaveLength(8);

    await act(async () => releaseSearch(searchResponse));
  });

  it("renders the Lab 3 experiment outcome on the Shop route it actually opens", async () => {
    window.history.replaceState(
      {},
      "",
      "/catalog?ask=1&mission=agentic-research&q=Compare%20quiet%20keyboards",
    );
    renderPage();

    expect(
      await screen.findByText(
        "Evidence is returned to the model but grounded synthesis cannot resolve it, so the agent refuses an unsupported recommendation.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("G-010 · Ready")).toBeTruthy();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByText("G-010 · Fixed")).toBeTruthy();
  });

  it("opens Ask Mosaic, renders grounded receipts, and cross-highlights products", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);

    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));

    // One ask surface, and it is the panel. This used to also morph the Shop
    // header into a second composer, so asking meant typing into one field and
    // then watching a different field slide in beside the answer.
    const panel = screen.getByRole("complementary", { name: "Ask Mosaic" });
    expect(panel.hasAttribute("aria-modal")).toBe(false);
    expect(document.querySelector(".shop-main")?.hasAttribute("inert")).toBe(false);
    expect(
      screen.getAllByRole("textbox", { name: "Ask Mosaic request" }),
    ).toHaveLength(1);
    expect(within(panel).queryByText("Shop context")).toBeNull();
    expect(
      within(panel).queryByLabelText("Active filters passed to Ask Mosaic"),
    ).toBeNull();

    // The entry state names the five tools registered in service/agent_tools.py,
    // by what each one does, with the function it calls beside it. Its whole
    // capability list used to be the bare Python names.
    const toolset = within(panel).getByRole("list", {
      name: "Tools available to the agent",
    });
    const capability = within(panel).getByText("What Mosaic can do").closest("details");
    expect(capability?.open).toBe(false);
    expect(
      within(toolset)
        .getAllByRole("listitem")
        .map((tool) => tool.textContent),
    ).toEqual([
      "Search the catalogsearch_products",
      "Compare options side by sidecompare_products",
      "Look up specs and reviewsget_product_evidence",
      "Replay the ranking signalsexplain_retrieval",
      "Write the cited recommendationsynthesize_cited_answer",
    ]);

    // Starters are queries from data/evals/demo_queries.jsonl, one per domain,
    // so the second consumer_electronics query must not appear. They used to be
    // three invented questions, one of which asked the agent to explain a
    // ranking before anything had been ranked.
    const starters = await within(panel).findByRole("list", {
      name: "Example questions",
    });
    expect(
      within(starters)
        .getAllByRole("button")
        .map((button) => button.querySelector("span")?.textContent),
    ).toEqual([examples[0].query, examples[2].query, examples[3].query]);

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const timeline = within(dialog).getByLabelText("Evidence timeline");
    expect(
      [...timeline.querySelectorAll(".ask-mosaic-stage-label")]
        .map((stage) => stage.textContent),
    ).toEqual(["Interpret", "Retrieve", "Compare", "Cite"]);
    // The settled state. While the run is live a step that just finished holds
    // its result open for a dwell, so this has to wait for the run to finish
    // before it can claim the cards are folded.
    await within(dialog).findByText("Final recommendation");
    // By class, not by role: an open card puts its candidate rows in the
    // timeline too, so `getAllByRole("button")` is not "the four stages".
    const stageButtons = [
      ...timeline.querySelectorAll<HTMLButtonElement>(".ask-mosaic-stage-summary"),
    ];
    expect(stageButtons).toHaveLength(4);
    expect(stageButtons.map((button) => button.getAttribute("aria-expanded"))).toEqual([
      "false",
      "false",
      "false",
      "true",
    ]);
    // Folded cards animate their height down and unmount the content after, so
    // these are reached once those exits finish.
    await waitFor(() => {
      expect(within(dialog).queryByText("Candidates retrieved")).toBeNull();
      expect(within(dialog).queryByText("Compared on catalog data")).toBeNull();
    });

    const evidence = await within(dialog).findByText("Evidence");
    expect(evidence.closest("details")?.open).toBe(false);
    expect(within(dialog).getByText("Final recommendation")).toBeTruthy();
    fireEvent.click(evidence);
    expect(within(dialog).getByText("Acoustic switch specification")).toBeTruthy();

    const activity = within(dialog).getByText("Activity receipts");
    expect(activity.closest("details")?.open).toBe(false);
    fireEvent.click(activity);
    expect(within(dialog).getByText("search_products")).toBeTruthy();
    expect(within(dialog).getByText(/max_price_cents/)).toBeTruthy();
    expect(screen.getByText("Ask Mosaic shortlist")).toBeTruthy();

    fireEvent.click(stageButtons[1]);
    expect(stageButtons[1].getAttribute("aria-expanded")).toBe("true");

    // Why this row is here, from the arm ranks and the reranker score. The row
    // used to read "RRF #2 · Final #1", which names two internal ranks and
    // answers nothing anybody asked. trigram.rank is null in this fixture, so
    // close spellings must not be claimed.
    expect(within(dialog).getByText("Best match")).toBeTruthy();
    const signals = within(dialog).getAllByLabelText(
      "Why this candidate was retrieved",
    );
    expect([...signals[0].querySelectorAll("span")].map((chip) => chip.textContent))
      .toEqual(["Your exact words", "What you meant", "Rerank 0.80"]);

    fireEvent.click(stageButtons[0]);
    expect(stageButtons[0].getAttribute("aria-expanded")).toBe("true");
    expect(within(dialog).getByText("Under $180")).toBeTruthy();
    expect(within(dialog).getByText("In stock only")).toBeTruthy();

    // The searches behind the shortlist, from AgentResponse.plan, which the
    // panel used to fetch and never render.
    expect(within(dialog).getByText("How I searched")).toBeTruthy();
    expect(within(dialog).getByText(agentResponse.plan[0].query)).toBeTruthy();
    expect(within(dialog).getByText("How I searched").closest("details")?.open).toBe(false);

    fireEvent.click(stageButtons[2]);
    expect(stageButtons[2].getAttribute("aria-expanded")).toBe("true");
    expect(within(dialog).getByText("Why 01 ranked first").closest("details")?.open).toBe(false);

    // Scoped to the candidate list: the answer now carries the same products as
    // buyable picks, so the product name matches a button in two places.
    const shortlist = dialog.querySelector<HTMLElement>(".ask-mosaic-shortlist");
    const shortlistButton = within(shortlist!).getByRole("button", {
      name: new RegExp(recommendations[0].model),
    });
    fireEvent.mouseEnter(shortlistButton);
    expect(
      document.querySelector(".shop-product-card.assist-highlighted"),
    ).not.toBeNull();
    fireEvent.mouseLeave(shortlistButton);
    expect(
      document.querySelector(".shop-product-card.assist-highlighted"),
    ).toBeNull();

    const linkedCatalogCard = document.querySelector(
      `[data-product-id="${recommendations[0].product_id}"]`,
    );
    expect(linkedCatalogCard).not.toBeNull();
    fireEvent.mouseEnter(linkedCatalogCard!);
    expect(
      within(shortlist!)
        .getByRole("button", { name: new RegExp(recommendations[0].model) })
        .closest("li")
        ?.classList.contains("highlighted"),
    ).toBe(true);
    fireEvent.mouseLeave(linkedCatalogCard!);

    // The composer empties, so the next thing typed is a follow-up rather than
    // an edit of the question already answered above it.
    expect(
      within(dialog).getByRole<HTMLInputElement>("textbox", {
        name: "Ask Mosaic request",
      }).value,
    ).toBe("");

    fireEvent.click(within(dialog).getByRole("button", { name: "Compare top two" }));
    await waitFor(() => expect(api.agentStream).toHaveBeenCalledTimes(2));
    expect(api.agentStream).toHaveBeenNthCalledWith(
      2,
      `Compare ${recommendations[0].model} with ${recommendations[1].model}`
        + " and explain the decisive trade-offs.",
      {},
      expect.any(Function),
      {
        previous_question: agentResponse.question,
        recommendations: recommendations.map((product) => ({
          product_id: product.product_id,
          title: product.title,
          model: product.model,
        })),
      },
    );

    // The follow-up appends to the conversation. It used to overwrite the single
    // stored response, so pressing "Compare top two" destroyed the answer that
    // named the two products being compared.
    expect(within(dialog).getAllByText("You asked")).toHaveLength(2);
    expect(within(dialog).getByText(agentResponse.question)).toBeTruthy();
    expect(
      within(dialog).getByText(
        `Compare ${recommendations[0].model} with ${recommendations[1].model}`
        + " and explain the decisive trade-offs.",
      ),
    ).toBeTruthy();
  });

  it("marks the answer as still being written while deltas arrive", async () => {
    let release = () => {};
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({
        type: "stage",
        id: "retrieve",
        title: "Retrieve",
        detail: "Searching the hybrid index.",
      });
      onEvent({ type: "answer_start", response: { ...agentResponse, answer: "" } });
      onEvent({ type: "answer_delta", delta: "Choose the first product" });
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    });

    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    expect(await within(dialog).findByText("Choose the first product")).toBeTruthy();
    expect(document.querySelector(".ask-mosaic-answer.streaming")).not.toBeNull();
    // Nothing to follow up on until the answer it would follow up on exists.
    expect(
      within(dialog).queryByRole("button", { name: "Compare top two" }),
    ).toBeNull();

    await act(async () => release());
    expect(document.querySelector(".ask-mosaic-answer.streaming")).toBeNull();
    expect(
      within(dialog).getByRole("button", { name: "Compare top two" }),
    ).toBeTruthy();
  });

  it("asks a starter question verbatim", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));

    fireEvent.click(await screen.findByRole("button", { name: examples[2].query }));

    await waitFor(() =>
      expect(api.agentStream).toHaveBeenCalledWith(
        examples[2].query,
        {},
        expect.any(Function),
        undefined,
      ),
    );
  });

  it("opens contextual filters and keeps active constraints visible", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);

    fireEvent.click(screen.getByRole("button", { name: "All filters" }));
    const dialog = screen.getByRole("dialog", { name: "Filters" });
    expect(dialog).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("radio", { name: "In stock" }));
    expect(await screen.findByRole("button", { name: /In stock/ })).toBeTruthy();
    expect(window.location.search).toContain("availability=in_stock");

    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    const assist = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const context = within(assist).getByLabelText(
      "Active filters passed to Ask Mosaic",
    );
    expect(within(context).getByText("Active filters")).toBeTruthy();
    expect(within(context).getByText("In stock")).toBeTruthy();
  });

  it("closes the sidecar and can restore the underlying Shop results", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    expect(screen.getByRole("complementary", { name: "Ask Mosaic" })).toBeTruthy();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    await screen.findByText("Ask Mosaic shortlist");

    fireEvent.click(
      within(screen.getByRole("complementary", { name: "Ask Mosaic" }))
        .getByRole("button", { name: "Close Ask Mosaic" }),
    );
    expect(screen.queryByRole("complementary", { name: "Ask Mosaic" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clear shortlist" }));
    expect(screen.queryByText("Ask Mosaic shortlist")).toBeNull();
    expect(screen.getByText(/of 200 products/)).toBeTruthy();
  });

  it("uses modal semantics, inert background, focus trap, and focus restoration on overlays", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    renderPage();
    await screen.findByText(catalog.products[0].model);
    const opener = screen.getByRole("button", { name: "Ask Mosaic" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Ask Mosaic" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.querySelector(".shop-main")?.hasAttribute("inert")).toBe(true);
    const close = within(dialog).getByRole("button", { name: "Close Ask Mosaic" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );
    close.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(focusable.at(-1));

    fireEvent.click(close);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Ask Mosaic" })).toBeNull()
    );
    expect(document.querySelector(".shop-main")?.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(opener);
  });
});
