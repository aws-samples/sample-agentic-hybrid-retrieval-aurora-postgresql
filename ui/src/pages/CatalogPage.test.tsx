// @vitest-environment jsdom

import {
  act,
  cleanup,
  configure,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AgentStreamEvent } from "../api";
import { CommerceProvider } from "../commerce";
import { CommerceDrawer } from "../components/CommerceDrawer";

// Ten assertions in this file await `findByText("Final recommendation")`, which
// `AskMosaic` renders only once `reveal.done`. `useTypewriterReveal` advances the
// answer a few characters per requestAnimationFrame, so those awaits are waiting
// on a real-time animation, not on a state update.
//
// The mocked answer is 64 characters and the hook adds 3 per frame at that
// backlog, so it needs 20 frames -- about 0.32s at 16ms. Against findBy's 1000ms
// default that is a 3.1x margin, and a loaded CI runner ate it twice in one day
// while the file passed 27/27 locally every time.
//
// 5000ms makes the budget ~15x the animation. A passing assertion still resolves
// the moment the label appears, so this costs nothing on success; only a genuine
// missing-element failure waits longer before reporting.
//
// The animation cannot simply be removed under test. Two attempts were measured
// and both deleted behaviour this file asserts: defaulting `matchMedia` to
// reduced motion makes the reveal synchronous but fails 15 tests, because the
// filter, focus-trap, sidecar and overlay tests depend on motion; stubbing
// requestAnimationFrame to run synchronously fails 11, including "marks the
// answer as still being written while deltas arrive", which requires the reveal
// to actually be paced. The paced reveal is under test, so the budget is what
// has to change.
//
// Vitest isolates test files by default -- there is no vitest config and no
// `test` block in vite.config.ts -- so this stays scoped to this file.
configure({ asyncUtilTimeout: 5000 });
import { stageDwellMs } from "../components/AskMosaic";
import { coreMosaicLabs } from "../labMissions";
import { showcaseCatalogPage } from "../showcase";
import { starterPath } from "../starters";
import type {
  AgentResponse,
  CatalogPage as CatalogPageResponse,
  CatalogSuggestion,
  HealthResponse,
  ProductDetail,
  ProductSummary,
  ReadinessResponse,
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
    health: vi.fn(),
    readiness: vi.fn(),
    product: vi.fn(),
  },
}));

/**
 * Shaped like `/api/retrieval/examples`, which serves `demo_queries.jsonl`
 * deduplicated in file order.
 *
 * Every row earns its place by making one rule in `starterPath` or
 * `starterExamples` falsifiable. Delete a row, or the rule it exists to prove,
 * and the expected order asserted below changes.
 *
 * - `D-001` (61 chars, `fts`+`vector`) is first in file order and longer than
 *   `D-005` (39 chars, same arm), which appears later. The `exact` pick has to
 *   take the shortest of its pool rather than the first, or `D-001` renders
 *   instead of `D-005`.
 * - `D-003` (41 chars) names both `fts` and `semantic`. `fts` must outrank
 *   `semantic` in `starterPath`, or `D-003` reclassifies into the `semantic`
 *   pool, where 41 beats `D-008`'s 44 and it becomes the "Meaning match" card
 *   instead.
 * - `D-004` (20 chars) names `pg_trgm`, `fts`, and `semantic`, shorter than
 *   every row in the `exact` pool. `pg_trgm` must outrank `fts` in
 *   `starterPath`, or `D-004` reclassifies as `exact` and wins that slot
 *   instead of `D-005`.
 * - `D-002` (53 chars, misspelled) is first among the misspelled rows and
 *   longer than `D-004` (20 chars), which appears later. The close-spelling box
 *   has to load the shortest of the lane rather than the first, or `D-002`
 *   loads instead of `D-004`.
 * - `D-007` (15 chars, `semantic` only) is shorter than every other row in the
 *   `semantic` pool, but its domain (`running_fitness`) is the one `D-005`
 *   already used for the `exact` pick. The `semantic` pick has to prefer an
 *   unused domain over the shortest query, or `D-007` wins instead of `D-008`.
 * - `D-006` (68 chars, `semantic`, unused domain `consumer_electronics`) is
 *   longer than `D-008`. Its presence proves the `semantic` pick is still the
 *   shortest of the *remaining* unused-domain rows once `D-007` is excluded,
 *   not merely the first one found.
 * - `D-008` (44 chars) names only `vector`, never the literal string
 *   `semantic`. It wins the `semantic` slot only if `starterPath` treats
 *   `vector` and `semantic` as the same arm, matching `TECHNIQUE_ARMS` in
 *   `starters.ts`.
 */
const examples: RetrievalExample[] = [
  {
    query_id: "D-001",
    domain: "consumer_electronics",
    query: "Find wireless noise-cancelling over-ear headphones under $200",
    expected_techniques: ["fts", "vector"],
    variant: 1,
  },
  {
    query_id: "D-002",
    domain: "running_fitness",
    query: "ergonmic ofice chair for ten long hour days at a desk",
    expected_techniques: ["pg_trgm", "semantic"],
    variant: 1,
  },
  {
    query_id: "D-003",
    domain: "home_office",
    query: "Quiet keyboard and mouse for shared desks",
    expected_techniques: ["fts", "semantic"],
    variant: 1,
  },
  {
    query_id: "D-004",
    domain: "consumer_electronics",
    query: "noice hedphones fast",
    expected_techniques: ["pg_trgm", "fts", "semantic"],
    variant: 1,
  },
  {
    query_id: "D-005",
    domain: "running_fitness",
    query: "Carbon-plated marathon shoes under $220",
    expected_techniques: ["fts", "vector"],
    variant: 1,
  },
  {
    query_id: "D-006",
    domain: "consumer_electronics",
    query: "A compact USB-C dock that can drive two monitors and charge a laptop",
    expected_techniques: ["semantic"],
    variant: 1,
  },
  {
    query_id: "D-007",
    domain: "running_fitness",
    query: "Trail shoes now",
    expected_techniques: ["semantic"],
    variant: 1,
  },
  {
    query_id: "D-008",
    domain: "home_office",
    query: "Quiet folding treadmill for small apartments",
    expected_techniques: ["vector"],
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

/**
 * A real `search_event_id` shape, because the Shop hand-off now carries it: the
 * Playground rejects anything that is not shaped like a persisted event id, so a
 * placeholder here would prove the wrong thing.
 */
const SEARCH_EVENT_ID = "9614ed9b-4ceb-4aad-9276-4e69af2231b9";
/** The run a second search serves, so "the run on the URL changed" is checkable
 * rather than inferred from the absence of the first one. */
const SECOND_EVENT_ID = "3f0a9d1c-6b2e-4c7a-8d51-2e9f4a6b7c80";

/** A search that has been made and has not answered yet: the window in which the
 * URL used to carry the previous run. */
function deferredSearch<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

const searchResponse: SearchResponse = {
  search_event_id: SEARCH_EVENT_ID,
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

const healthFixture: HealthResponse = {
  status: "ok",
  service: "catalog-hybrid-retrieval",
  models: {
    embedding: "cohere.embed-v4",
    rerank: "cohere.rerank-v3-5",
    agent: "anthropic.claude-sonnet-4-6",
    synthesis: "anthropic.claude-sonnet-4-6",
  },
  code_editor_url: "https://code.mosaic-workshop.example",
};

/**
 * Every retrieval index present and the corpus seeded: nothing about the
 * environment stands between the participant and Lab 1's own defect.
 */
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
    evidence_product_count: 120,
    missing_retrieval_indexes: [],
    missing_retrieval_functions: [],
  },
  configured_models: {
    embedding: "us.cohere.embed-v4:0",
    rerank: "cohere.rerank-v3-5:0",
    agent: "anthropic.claude-sonnet-4-6",
    synthesis: "anthropic.claude-sonnet-4-6",
  },
  bedrock_credentials: { ready: true },
};

/** Lab 1's own mission, read from the manifest rather than restated here. */
const lab1 = coreMosaicLabs[0];

/**
 * One eligible result for Lab 1's request.
 *
 * Every field the outcome reads is set deliberately: the domain, the price under
 * the $200 ceiling and the in-stock availability are what `retrievalLabOutcome`
 * checks for eligibility, and the trigram signals are what separate "the target
 * came back" from "the target came back through the repaired arm".
 */
function lab1Result(
  productId: number,
  finalRank: number,
  fromTrigram: boolean,
): ProductSummary {
  return {
    ...rankedProduct(catalog.products[0], finalRank),
    product_id: productId,
    title: productId === 2
      ? "Sonora WH-C720 Wireless Noise-Cancelling Headphones"
      : `Alternative headphones ${productId}`,
    domain: "consumer_electronics",
    price_cents: 18900,
    availability: "in_stock",
    signals: {
      fts: { rank: null, raw_score: null, rrf_contribution: null },
      trigram: fromTrigram
        ? { rank: 1, raw_score: 0.42, rrf_contribution: 0.016 }
        : { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: finalRank, raw_score: 0.2, rrf_contribution: 0.016 },
      rrf_score: fromTrigram ? 0.032 : 0.016,
      pre_rerank_rank: finalRank,
      pre_rerank_score: 0.032,
      rerank_score: 0.9 - finalRank / 10,
      final_rank: finalRank,
      score_semantics: "rank_fusion_then_bounded_rerank",
    },
  };
}

/**
 * The run Lab 1's own chip produces: its query, under its own gates.
 *
 * `applied_filters` has to echo the mission's gates exactly, because the callout
 * refuses to grade a run that asked a different question. `trigram_in_pool` is
 * the diagnostic that distinguishes a disconnected arm from an arm that ran and
 * found nothing.
 */
function lab1Search(targetPresent: boolean): SearchResponse {
  return {
    search_event_id: SEARCH_EVENT_ID,
    query: lab1.query,
    normalized_query: lab1.query,
    applied_filters: {
      domain: "consumer_electronics",
      max_price_cents: 20000,
      in_stock_only: true,
    },
    results: targetPresent
      ? [lab1Result(2, 1, true), lab1Result(3, 2, false)]
      : [lab1Result(3, 1, false), lab1Result(5, 2, false)],
    diagnostics: {
      ...searchResponse.diagnostics!,
      candidate_counts: {
        fused_pool: 18,
        trigram_in_pool: targetPresent ? 4 : 0,
      },
    },
  };
}

const productDetail: ProductDetail = {
  ...recommendations[0],
  long_description: "A hushed board measured for shared desks.",
  canonical_group_id: "group-1",
  source_system: "mosaic_catalog",
  updated_at: "2026-08-01T00:00:00Z",
  media: [],
  reviews: [],
};

describe("CatalogPage", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("scrollTo", vi.fn());
    window.history.replaceState({}, "", "/catalog");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.suggestions).mockReset();
    vi.mocked(api.search).mockReset();
    vi.mocked(api.agentStream).mockReset();
    vi.mocked(api.examples).mockReset();
    vi.mocked(api.health).mockReset();
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.product).mockReset();
    vi.mocked(api.health).mockResolvedValue(healthFixture);
    vi.mocked(api.readiness).mockResolvedValue(healthyReadiness);
    vi.mocked(api.product).mockResolvedValue(productDetail);
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
        path: "full_retrieval",
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
        path: "full_retrieval",
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
    const timeline = within(dialog).getByLabelText("Steps I took");
    await waitFor(() =>
      expect(within(dialog).queryByText("The shortlist")).not.toBeNull());

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
    // Exactly one result is expanded at a time. The previous implementation
    // kept Interpret open for 2.2 seconds after Retrieve opened, so the next
    // stages were pushed below the drawer while two large panels overlapped.
    expect(running[0].getAttribute("aria-expanded")).toBe("false");
    // The outgoing content remains mounted for its 240ms exit. Keying the whole
    // disclosure by state used to destroy it immediately, bypassing that exit.
    expect(within(dialog).getByText("Filters I searched with")).toBeTruthy();
    await waitFor(() =>
      expect(within(dialog).queryByText("Filters I searched with")).toBeNull());
    // Compare and Cite have not run. Candidate rows exist, so their panels
    // could be built - a pending stage must still disclose nothing.
    expect(running[2].hasAttribute("aria-expanded")).toBe(false);
    expect(running[2].disabled).toBe(true);
    expect(within(dialog).queryByText("Side by side, on catalog data")).toBeNull();

    release();
    // A synchronous finish may put Rank and Answer in one React batch. The
    // presentation queue must still show Rank before answer prose can mount.
    expect(within(dialog).queryByText("Final recommendation")).toBeNull();
    await waitFor(
      () => expect(stageCards()[2].getAttribute("aria-expanded")).toBe("true"),
      { timeout: stageDwellMs * 2 + 2000 },
    );
    expect(within(dialog).getByText("Side by side, on catalog data")).toBeTruthy();
    expect(within(dialog).queryByText("Final recommendation")).toBeNull();
    await within(dialog).findByText("Final recommendation");
    // Finishing folds the retrieve card back up, leaving the answer open.
    expect(stageCards().map((card) => card.getAttribute("aria-expanded")))
      .toEqual(["false", "false", "false", "true"]);
    // This test waits through the real presentation timings on purpose: the
    // catalog reveal, two stage dwells plus their exits, and the answer
    // typewriter. Together they exceed vitest's 5000ms default on a loaded CI
    // runner (Project CI timed out here on 2026-09-04 after passing locally),
    // so the budget is sized to the dwell it already waits for.
  }, stageDwellMs * 4 + 10_000);

  it("counts the wait on the step that is working, without restarting it", async () => {
    // Grounded synthesis cannot show a word until the answer has been checked
    // against the citations it claims, which measured fourteen seconds on the live
    // cluster. Nothing was counting, so the last card sat unchanged for all
    // fourteen and the finished answer then appeared at once: a hang, then a snap.
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const synthesisStage = {
      type: "stage",
      id: "answer",
      path: "focused_follow_up",
      title: "Compose cited answer",
      detail: "Preparing the citation-bounded answer of record.",
    } as const;
    let emit: ((event: AgentStreamEvent) => void) | null = null;
    vi.mocked(api.agentStream).mockImplementation(async (_q, _f, onEvent) => {
      emit = onEvent;
      onEvent(synthesisStage);
      await held;
      onEvent({ type: "complete", response: agentResponse });
    });

    let now = 1_000;
    const clock = vi.spyOn(Date, "now").mockImplementation(() => now);
    try {
      renderPage();
      await screen.findByText(catalog.products[0].model);
      fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
      fireEvent.change(
        screen.getByRole("textbox", { name: "Ask Mosaic request" }),
        { target: { value: agentResponse.question } },
      );
      fireEvent.click(screen.getByRole("button", { name: "Send request" }));
      const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
      const timeline = within(dialog).getByLabelText("Steps I took");
      const seconds = () => [
        ...timeline.querySelectorAll(".ask-mosaic-stage-elapsed"),
      ].map((reading) => Number.parseInt(reading.textContent ?? "", 10));

      // Nothing yet: a step that has just started has no elapsed time to report,
      // and "0s" would be a reading rather than the absence of one.
      expect(seconds()).toEqual([]);

      now = 10_000;
      await waitFor(() => expect(seconds()).toHaveLength(1), {
        timeout: stageDwellMs * 2 + 2000,
      });
      // One reading, on the one step that is working. A finished step reports its
      // state, not a clock that would keep running after it stopped.
      expect(seconds()[0]).toBeGreaterThanOrEqual(9);
      const beforeRepeat = seconds()[0];

      // The service announces this step twice: once when synthesis is dispatched
      // and again with a fuller detail line when it returns. Restarting on the
      // second would report the sub-second write instead of the wait a reader sat
      // through, which is the number this exists to show - so a restart shows up
      // here as a reading of about 2 rather than about 11.
      now = 12_000;
      act(() => {
        emit?.({
          ...synthesisStage,
          detail: "Delivering only claims grounded in returned catalog sources.",
        });
      });
      await waitFor(
        () => expect(seconds()[0]).toBeGreaterThanOrEqual(beforeRepeat + 2),
        { timeout: 2000 },
      );

      release();
      await within(dialog).findByText("Final recommendation");
      // Settled: no step is working, so nothing is counting.
      expect(seconds()).toEqual([]);
    } finally {
      release();
      clock.mockRestore();
    }
  });

  it("clears the conversation without dismissing the panel", async () => {
    // Shop's "Clear shortlist" closes the panel because it is a Shop control. This
    // one has to leave the reader inside the conversation it emptied, back on the
    // entry state, or clearing a thread means losing the thing you were reading.
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    // Nothing to discard yet.
    expect(screen.queryByRole("button", { name: "Clear chat" })).toBeNull();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    await within(dialog).findByText("Final recommendation");

    fireEvent.click(within(dialog).getByRole("button", { name: "Clear chat" }));
    expect(
      screen.getByRole("complementary", { name: "Ask Mosaic" }),
    ).toBeTruthy();
    expect(screen.queryByText("Final recommendation")).toBeNull();
    expect(screen.queryByText(agentResponse.question)).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear chat" })).toBeNull();
    // Back on the entry state, ready for the next question.
    expect(
      within(dialog).getByRole("list", { name: "Example questions" }),
    ).toBeTruthy();
  });

  it("aborts an in-flight request when the conversation is cleared", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, _onEvent, _context, options) => {
        requestSignal = options?.signal;
        await new Promise<void>((_resolve, reject) => {
          requestSignal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      },
    );

    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    await waitFor(() => expect(requestSignal).toBeDefined());

    fireEvent.click(within(dialog).getByRole("button", { name: "Clear chat" }));

    expect(requestSignal?.aborted).toBe(true);
    expect(within(dialog).queryByText(agentResponse.question)).toBeNull();
    expect(
      within(dialog).getByRole("list", { name: "Example questions" }),
    ).toBeTruthy();
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

  it("opens a chosen pick as a drawer beside the conversation, not a navigation", async () => {
    // Going deeper on a pick used to route to /products/:id, which tore the
    // shopper out of the conversation. The full catalog row now arrives as a
    // slide-over on the same page.
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
    fireEvent.click(
      within(picks).getByRole("button", {
        name: new RegExp(recommendations[0].model),
      }),
    );

    // Still on Shop, with the row fetched into a dialog above it.
    expect(window.location.pathname).toBe("/catalog");
    const drawer = await screen.findByRole("dialog", { name: "Product details" });
    expect(api.product).toHaveBeenCalledWith(recommendations[0].product_id);
    await within(drawer).findByText(productDetail.long_description);
    expect(
      within(drawer).getByRole("heading", { name: productDetail.title }),
    ).toBeTruthy();
    expect(
      within(drawer).getByRole("link", { name: /Full product page/ }),
    ).toBeTruthy();

    fireEvent.click(
      within(drawer).getByRole("button", { name: "Close product details" }),
    );
    // The drawer glides off, so its removal ends an exit animation rather
    // than landing on the same frame as the click.
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Product details" })).toBeNull());
    expect(
      screen.getByRole("complementary", { name: "Ask Mosaic" }),
    ).toBeTruthy();
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
        "Search in your own words, browse with intention, or ask Mosaic for help deciding.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/photographed in one light/i)).toBeNull();
    const search = screen.getByRole("region", { name: "Mosaic product search" });
    expect(within(search).getAllByRole("button")).toHaveLength(1);
    const searchSubmit = within(search).getByRole("button", { name: "Search" });
    expect(searchSubmit.textContent).toBe("");
    expect(searchSubmit.querySelector("svg")).toBeTruthy();
    expect(document.querySelectorAll(".shop-suggested > button")).toHaveLength(3);
    expect(
      screen.getByRole("complementary", { name: "What Ask Mosaic does" })
        .contains(screen.getByRole("button", { name: "Ask Mosaic" })),
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "Ask Mosaic" }).classList
        .contains("mosaic-ask-button"),
    ).toBe(true);
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

    expect(await screen.findByText("Results for")).toBeTruthy();
    expect(screen.getByText(/chosen from 18 candidates/)).toBeTruthy();
    expect(screen.queryByText(/fused candidates/)).toBeNull();
    const rankingReceipt = screen
      .getByText("Why these results, in this order")
      .closest("details");
    expect(rankingReceipt?.open).toBe(false);
    // "Why this match", not "Why ranked #3": a shopper choosing between two chairs
    // is asking what Mosaic noticed, and the position is inside.
    const productReceipt = screen
      .getAllByText("Why this match")[0]
      .closest("details");
    expect(productReceipt?.open).toBe(false);
    fireEvent.click(within(productReceipt!).getByText("Why this match"));
    // Only the arms that found this row appear: a "Close spelling" row on a
    // product the trigram arm never returned would be a rank Mosaic invented.
    expect(within(productReceipt!).getByText("Exact terms")).toBeTruthy();
    expect(within(productReceipt!).queryByText("Close spelling")).toBeNull();
    expect(within(productReceipt!).getByText("Before reranking")).toBeTruthy();
    expect(within(productReceipt!).getByText("Final position")).toBeTruthy();
    expect(within(productReceipt!).getAllByText("#1").length).toBeGreaterThan(0);
    // No mechanism names on a product card, in any form.
    expect(productReceipt!.textContent).not.toMatch(/FTS|TRGM|pg_trgm|HNSW|RRF/);
    expect(screen.queryByText("RRF #2")).toBeNull();
    expect(api.catalog).not.toHaveBeenCalled();
  });

  it("hands the Playground the run it served, not just the words that produced it", async () => {
    // The link used to carry the query and the gates only, so following it made
    // the Playground re-run the request and mint a second event. The run behind
    // the results the shopper is looking at was then unreachable, and nothing
    // downstream could compare against it.
    window.history.replaceState({}, "", "/catalog?q=quiet%20keyboard");
    renderPage();

    const link = await screen.findByRole("link", {
      name: /See how this was retrieved/,
    });
    const params = new URLSearchParams(link.getAttribute("href")!.split("?")[1]);

    expect(params.get("q")).toBe("quiet keyboard");
    expect(params.get("event")).toBe(SEARCH_EVENT_ID);
  });

  it("records the served run on its own URL, so the header hand-off carries it too", async () => {
    // The header's Playground entry is built from the Shop URL alone, so a run
    // recorded only in component state would reach one hand-off path and not the
    // other.
    window.history.replaceState({}, "", "/catalog?q=quiet%20keyboard");
    renderPage();

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("event"))
        .toBe(SEARCH_EVENT_ID);
    });
    expect(new URLSearchParams(window.location.search).get("q")).toBe("quiet keyboard");
  });

  it("retires the recorded run the moment a second search replaces it", async () => {
    // The URL said `?q=<new query>&event=<run that answered the old one>` for as
    // long as the second search was in flight, and the Playground took delivery
    // of that link: it read the old run back and announced it as the exact run
    // behind results the shopper had never seen.
    window.history.replaceState({}, "", "/catalog?q=quiet%20keyboard");
    renderPage();
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("event"))
        .toBe(SEARCH_EVENT_ID);
    });

    const secondRun = { ...searchResponse, search_event_id: SECOND_EVENT_ID };
    const inFlight = deferredSearch<SearchResponse>();
    vi.mocked(api.search).mockReturnValueOnce(inFlight.promise);
    const input = screen.getByRole("combobox", { name: "Product search" });
    fireEvent.change(input, { target: { value: "silent switches" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("q"))
        .toBe("silent switches");
    });
    expect(new URLSearchParams(window.location.search).get("event")).toBeNull();

    await act(async () => {
      inFlight.resolve(secondRun);
    });

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("event"))
        .toBe(SECOND_EVENT_ID);
    });
  });

  it("does not re-stamp the pre-filter run onto the URL when filters are cleared", async () => {
    // Clearing the gates builds a fresh URL without the run on it, and the
    // recording effect used to put it straight back: same query, a pool that no
    // longer exists.
    window.history.replaceState({}, "", "/catalog?q=quiet%20keyboard&brand=Sonorra");
    renderPage();
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("event"))
        .toBe(SEARCH_EVENT_ID);
    });

    const inFlight = deferredSearch<SearchResponse>();
    vi.mocked(api.search).mockReturnValueOnce(inFlight.promise);
    fireEvent.click(screen.getAllByRole("button", { name: "Clear all" })[0]);

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("brand")).toBeNull();
    });
    expect(new URLSearchParams(window.location.search).get("q")).toBe("quiet keyboard");
    expect(new URLSearchParams(window.location.search).get("event")).toBeNull();

    await act(async () => {
      inFlight.resolve({ ...searchResponse, search_event_id: SECOND_EVENT_ID });
    });

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("event"))
        .toBe(SECOND_EVENT_ID);
    });
  });

  it("scrolls a Discover handoff to results and offers Ask Mosaic beside them", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    window.history.replaceState(
      {},
      "",
      "/catalog?q=quiet%20keyboard&view=results",
    );

    renderPage();

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      });
    });
    const prompt = screen.getByRole("button", {
      name: "Try Ask Mosaic with these results",
    });
    fireEvent.click(prompt);

    expect(screen.getByRole("complementary", { name: "Ask Mosaic" })).toBeTruthy();
    // The rail glides off rather than unmounting flat, so its removal is the
    // end of an exit animation, not the same frame as the click.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Try Ask Mosaic with these results",
        }),
      ).toBeNull());
  });

  it("offers keyboard-selectable catalog matches before hybrid retrieval", async () => {
    renderPage();
    const input = screen.getByRole("combobox", { name: "Product search" });

    fireEvent.change(input, { target: { value: "a" } });
    await new Promise((resolve) => window.setTimeout(resolve, 220));
    expect(api.suggestions).not.toHaveBeenCalled();
    expect(
      screen.getByText("Keep typing: use at least 2 characters."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search" }).hasAttribute("disabled"))
      .toBe(true);
    fireEvent.submit(input.closest("form")!);
    expect(api.search).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "aura" } });
    expect(
      screen.queryByText("Keep typing: use at least 2 characters."),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Search" }).hasAttribute("disabled"))
      .toBe(false);
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

  it("does not duplicate the visible suggested searches inside an empty field", () => {
    renderPage();
    const input = screen.getByRole("combobox", { name: "Product search" });

    expect(document.querySelector(".catalog-idle-suggestion")).toBeNull();
    fireEvent.submit(input.closest("form")!);
    expect(api.search).not.toHaveBeenCalled();
  });

  it("shows a catalog failure instead of substituting showcase products", async () => {
    vi.mocked(api.catalog).mockRejectedValue(new Error("Aurora catalog is unavailable"));
    renderPage();

    expect(
      await screen.findByText("Aurora catalog is unavailable"),
    ).toBeTruthy();
    expect(document.querySelectorAll("[data-product-id]")).toHaveLength(0);
  });

  it("keeps the newest catalog page when an older request resolves last", async () => {
    const pending: Array<(value: CatalogPageResponse) => void> = [];
    vi.mocked(api.catalog).mockImplementation(
      () => new Promise<CatalogPageResponse>((resolve) => pending.push(resolve)),
    );
    const latestProduct = {
      ...catalog.products[0],
      product_id: 987_654,
      model: "Newest filter result",
      title: "Newest filter result",
    };

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Running & fitness" }));
    await waitFor(() => expect(api.catalog).toHaveBeenCalledTimes(2));

    await act(async () => pending[1]({
      ...catalog,
      products: [latestProduct],
      offset: 0,
      total: 1,
    }));
    expect(await screen.findByText("Newest filter result")).toBeTruthy();

    await act(async () => pending[0](catalog));
    expect(screen.getByText("Newest filter result")).toBeTruthy();
    expect(screen.queryByText(catalog.products[0].model)).toBeNull();
  });

  it("renders zero-result catalog arithmetic without an impossible range", async () => {
    vi.mocked(api.catalog).mockResolvedValue({
      ...catalog,
      products: [],
      total: 0,
    });
    renderPage();

    await waitFor(() => expect(
      document.querySelector(".shop-results-heading")?.textContent,
    ).toContain("0 products"));
    expect(document.querySelector(".shop-results-heading")?.textContent)
      .not.toContain("1-0");
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
    expect(allProducts.getAttribute("aria-pressed")).toBe("true");
    expect(running.getAttribute("aria-pressed")).toBe("false");
    expect(allProducts.querySelector(".shop-domain-indicator")).toBeTruthy();
    expect(document.querySelectorAll(".shop-domain-indicator")).toHaveLength(1);

    fireEvent.click(running);

    await waitFor(() => {
      expect(window.location.search).toContain("domain=running_fitness");
      expect(running.querySelector(".shop-domain-indicator")).toBeTruthy();
    });
    expect(allProducts.getAttribute("aria-pressed")).toBe("false");
    expect(running.getAttribute("aria-pressed")).toBe("true");
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

    const trace = await screen.findByLabelText("What this search is doing");
    expect(
      within(trace).getByText(
        "This is the same path every Mosaic search takes. The steps are not streamed one by one, so nothing here claims an order it cannot see.",
      ),
    ).toBeTruthy();
    // The seven steps in the storefront's words. This list used to print "Cohere
    // Embed v4 / FTS / pg_trgm / HNSW / SQL eligibility / RRF / Cohere Rerank" to a
    // shopper waiting for products.
    expect(
      [...trace.querySelectorAll("li")].map((step) => step.textContent),
    ).toEqual([
      "Understanding your words",
      "Exact terms",
      "Close spelling",
      "Meaning match",
      "Only what you can buy",
      "Combining the results",
      "Reranking the shortlist",
    ]);
    expect(trace.textContent).not.toMatch(/FTS|pg_trgm|HNSW|RRF|Cohere/);
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

    await screen.findByRole("complementary", { name: "Ask Mosaic" });
    expect(document.querySelector(".lab-outcome")).toBeNull();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByText("Grounding verified")).toBeTruthy();
    expect(
      screen.getByText("Every citation resolves to retrieved evidence"),
    ).toBeTruthy();
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
      within(panel).queryByLabelText("Your preferences, passed to Ask Mosaic"),
    ).toBeNull();

    // The entry state names the five tools registered in service/agent_tools.py,
    // by what each one does, with the function it calls beside it. Its whole
    // capability list used to be the bare Python names.
    const toolset = within(panel).getByRole("list", {
      name: "Tools available to the agent",
    });
    const capability = within(panel).getByText("What I can do").closest("details");
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

    // Starters are vetted questions, one per clickable retrieval arm. Eval
    // provenance and expected-technique tags stay off the shopper surface; the
    // completed run is where actual retrieval evidence belongs.
    const starters = await within(panel).findByRole("list", {
      name: "Example questions",
    });
    expect(
      within(starters)
        .getAllByRole("button")
        .map((button) => [
          button.querySelector(".ask-mosaic-starter-path")?.textContent,
          button.querySelector(".ask-mosaic-starter-query")?.textContent,
        ]),
    ).toEqual([
      ["Exact terms", examples[4].query],
      ["Meaning match", examples[7].query],
      // The close-spelling lane, which says what it does instead of printing the
      // query it loads. `D-004` over `D-002` because it is the shorter of the two
      // misspelled rows, so what lands in the composer is short enough to read the
      // misspellings in before sending it.
      ["Close spelling", "Search with typos in it"],
    ]);
    expect(starters.textContent).not.toContain("eval set");
    expect(starters.querySelector(".ask-mosaic-starter-arms")).toBeNull();
    // No card prints a misspelling. The eval set's fuzzy queries are misspelled on
    // purpose and the two run-on-click cards print a starter verbatim on a button
    // in Mosaic's own voice, so offering one shipped a spelling mistake as the
    // store's suggestion. The third card reaches the same lane without printing
    // one, which is why this assertion still has to hold with it on screen.
    for (const word of ["ergonmic", "ofice", "noice", "hedphones"]) {
      expect(starters.textContent).not.toContain(word);
    }

    // It loads, it does not send. The typo has to be in the shopper's input and
    // sent by the shopper, or the store authored it after all.
    fireEvent.click(
      within(starters).getByRole("button", {
        name: "Put a misspelled search in the box, ready to send",
      }),
    );
    expect(
      screen.getByRole<HTMLInputElement>("textbox", { name: "Ask Mosaic request" })
        .value,
    ).toBe(examples[3].query);
    expect(api.agentStream).not.toHaveBeenCalled();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const timeline = within(dialog).getByLabelText("Steps I took");
    expect(
      [...timeline.querySelectorAll(".ask-mosaic-stage-label")]
        .map((stage) => stage.textContent),
    ).toEqual(["Understanding", "Recommendations", "Compare", "Why these"]);
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
      expect(within(dialog).queryByText("The shortlist")).toBeNull();
      expect(
        within(dialog).queryByText("Side by side, on catalog data"),
      ).toBeNull();
    });

    const evidence = await within(dialog).findByText("Evidence it cited");
    expect(evidence.closest("details")?.open).toBe(false);
    expect(within(dialog).getByText("Final recommendation")).toBeTruthy();
    fireEvent.click(evidence);
    expect(within(dialog).getByText("Acoustic switch specification")).toBeTruthy();

    const activity = within(dialog).getByText("What the agent did");
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
      // The same three words the product card and the Playground use.
      .toEqual(["Exact terms", "Meaning match", "Rerank score 0.80"]);

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
    expect(within(dialog).getByText("Why this one is first").closest("details")?.open).toBe(false);

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
        previous_agent_run_id: agentResponse.agent_run_id,
        previous_question: agentResponse.question,
        recommendations: recommendations.map((product) => ({
          product_id: product.product_id,
          title: product.title,
          model: product.model,
        })),
      },
      { signal: expect.any(AbortSignal) },
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

  it("shows a compact evidence path for a closed-world follow-up", async () => {
    let invocation = 0;
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, onEvent) => {
        invocation += 1;
        if (invocation === 1) {
          onEvent({
            type: "stage",
            id: "retrieve",
            path: "full_retrieval",
            title: "Retrieve",
            detail: "Searching the hybrid index.",
          });
        } else {
          onEvent({
            type: "stage",
            id: "rank",
            path: "focused_follow_up",
            title: "Inspect prior shortlist",
            detail: "Reading only the records needed for this follow-up.",
          });
        }
        onEvent({ type: "complete", response: agentResponse });
      },
    );

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

    fireEvent.click(within(dialog).getByRole("button", { name: "Compare top two" }));
    await waitFor(() => expect(api.agentStream).toHaveBeenCalledTimes(2));

    const timelines = within(dialog).getAllByLabelText("Steps I took");
    const followupCards = timelines[1].querySelectorAll(".ask-mosaic-stage-summary");
    expect(followupCards).toHaveLength(3);
    expect(
      [...timelines[1].querySelectorAll(".ask-mosaic-stage-label")].map(
        (stage) => stage.textContent,
      ),
    ).toEqual(["Understanding", "Compare", "Why these"]);
    expect(within(timelines[1]).queryByText("Recommendations")).toBeNull();
  });

  it("returns a new-candidate follow-up to the full retrieval path", async () => {
    let invocation = 0;
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, onEvent) => {
        invocation += 1;
        onEvent({
          type: "stage",
          id: "retrieve",
          path: "full_retrieval",
          title: "Retrieve",
          detail: "Searching the hybrid index.",
        });
        onEvent({ type: "complete", response: agentResponse });
      },
    );

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

    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: "Show me cheaper alternatives." } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Send request" }));
    await waitFor(() => expect(api.agentStream).toHaveBeenCalledTimes(2));

    const timelines = within(dialog).getAllByLabelText("Steps I took");
    const followupCards = timelines[1].querySelectorAll(".ask-mosaic-stage-summary");
    expect(followupCards).toHaveLength(4);
    expect(within(timelines[1]).getByText("Recommendations")).toBeTruthy();
    expect(within(timelines[1]).getByText("Compare")).toBeTruthy();
    expect(invocation).toBe(2);
  });

  it("marks the answer as still being written while deltas arrive", async () => {
    let release = () => {};
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({
        type: "stage",
        id: "retrieve",
        path: "full_retrieval",
        title: "Retrieve",
        detail: "Searching the hybrid index.",
      });
      onEvent({ type: "answer_start", response: { ...agentResponse, answer: "" } });
      onEvent({ type: "answer_delta", delta: "Choose the first product" });
      await new Promise<void>((resolve) => {
        release = resolve;
      });
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
    expect(await within(dialog).findByText("Choose the first product")).toBeTruthy();
    expect(document.querySelector(".ask-mosaic-answer.streaming")).not.toBeNull();
    // Nothing to follow up on until the answer it would follow up on exists.
    expect(
      within(dialog).queryByRole("button", { name: "Compare top two" }),
    ).toBeNull();

    await act(async () => release());
    await within(dialog).findByText("Final recommendation");
    expect(document.querySelector(".ask-mosaic-answer.streaming")).toBeNull();
    expect(
      within(dialog).getByRole("button", { name: "Compare top two" }),
    ).toBeTruthy();
  });

  it("does not promote an interrupted answer stream to a final recommendation", async () => {
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, onEvent) => {
        onEvent({
          type: "stage",
          id: "answer",
          path: "full_retrieval",
          title: "Compose cited answer",
          detail: "Preparing the citation-bounded answer of record.",
        });
        onEvent({
          type: "answer_start",
          response: { ...agentResponse, answer: "" },
        });
        onEvent({ type: "answer_delta", delta: "Choose the first product" });
        throw new Error("Connection dropped before completion");
      },
    );

    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    expect(
      await within(dialog).findByText("Connection dropped before completion"),
    ).toBeTruthy();
    expect(within(dialog).getByText("Needs attention")).toBeTruthy();
    expect(within(dialog).queryByText("Final recommendation")).toBeNull();
    expect(
      within(dialog).queryByRole("button", { name: "Compare top two" }),
    ).toBeNull();
  });

  it("stops auto-following when the reader scrolls back through evidence", async () => {
    let emit: ((event: AgentStreamEvent) => void) | undefined;
    let release = () => {};
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, onEvent) => {
        emit = onEvent;
        onEvent({
          type: "stage",
          id: "retrieve",
          path: "full_retrieval",
          title: "Retrieve",
          detail: "Searching the hybrid index.",
        });
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      },
    );

    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const thread = dialog.querySelector<HTMLElement>(".ask-mosaic-body")!;
    Object.defineProperties(thread, {
      clientHeight: { configurable: true, value: 300 },
      scrollHeight: { configurable: true, value: 1200 },
      scrollTop: { configurable: true, writable: true, value: 1200 },
    });
    thread.scrollTop = 120;
    fireEvent.scroll(thread);
    act(() => {
      emit?.({
        type: "stage",
        id: "rank",
        path: "full_retrieval",
        title: "Rank",
        detail: "Comparing the shortlist.",
      });
    });

    await waitFor(
      () => expect(
        within(dialog).getByText("How they compare"),
      ).toBeTruthy(),
      { timeout: stageDwellMs * 3 + 2000 },
    );
    expect(thread.scrollTop).toBe(120);
    release();
  });

  it("announces stage boundaries and final completion without announcing deltas", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const dialog = screen.getByRole("complementary", { name: "Ask Mosaic" });
    expect(
      await within(dialog).findByText("Ask Mosaic recommendation complete."),
    ).toBeTruthy();
    expect(
      within(dialog).getAllByRole("status")
        .filter((status) => status.textContent?.includes("recommendation complete")),
    ).toHaveLength(1);
  });

  it("asks a starter question verbatim", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));

    fireEvent.click(await screen.findByRole("button", { name: examples[4].query }));

    await waitFor(() =>
      expect(api.agentStream).toHaveBeenCalledWith(
        examples[4].query,
        {},
        expect.any(Function),
        undefined,
        { signal: expect.any(AbortSignal) },
      ),
    );
  });

  it("shows a distinct retrieval-arm label on every starter card, never repeated", async () => {
    // The bug this guards against: `starterPath` used to fall through to a
    // catch-all "plain" path for any query naming `semantic`/`vector` without
    // also naming `fts` or `pg_trgm`. Two of the rendered cards then both read
    // "Plain language" and no card ever read "Meaning match", even though the
    // underlying queries exercised different arms.
    renderPage();
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));

    const starters = await screen.findByRole("list", { name: "Example questions" });
    const pathLabels = within(starters)
      .getAllByRole("button")
      .map((button) => button.querySelector(".ask-mosaic-starter-path")?.textContent);

    // Witness: exactly three cards rendered - two clickable arms plus the
    // close-spelling box - a literal independent of the uniqueness check
    // below, so this cannot pass on an empty or short-circuited list.
    expect(pathLabels).toHaveLength(3);
    // No two cards carry the same label: the set of labels is exactly the
    // three distinct retrieval-arm names, matching `armLabel` in
    // `retrievalLanguage.ts` rather than a locally invented fourth string.
    expect(new Set(pathLabels)).toEqual(
      new Set(["Exact terms", "Meaning match", "Close spelling"]),
    );
    expect(new Set(pathLabels).size).toBe(3);
  });

  it("throws rather than silently mislabeling a row that names no known retrieval arm", () => {
    // `starterPath` used to fall through to a catch-all "plain" label for
    // anything it could not classify. Every real `demo_queries.jsonl` row
    // names at least one of pg_trgm/fts/semantic/vector, so a row naming none
    // of them is a fixture-contract violation, not a case the panel should
    // silently render a label for.
    expect(() =>
      starterPath({
        query_id: "D-999",
        domain: "consumer_electronics",
        query: "malformed row with no retrieval arm",
        expected_techniques: ["rerank", "filters"],
        variant: 1,
      }),
    ).toThrow(/no known retrieval arm/);
  });

  it("opens contextual filters and keeps active constraints visible", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);

    fireEvent.click(screen.getByRole("button", { name: "All filters" }));
    const dialog = screen.getByRole("dialog", { name: "Filters" });
    expect(dialog).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Category" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    expect(
      within(dialog).getByRole("button", { name: "Availability" })
        .getAttribute("aria-expanded"),
    ).toBe("false");

    fireEvent.click(within(dialog).getByRole("button", { name: "Availability" }));
    fireEvent.click(within(dialog).getByRole("radio", { name: "In stock" }));
    expect(window.location.search).toContain("availability=in_stock");
    fireEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("button", { name: /In stock/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    const assist = screen.getByRole("complementary", { name: "Ask Mosaic" });
    const context = within(assist).getByLabelText(
      "Your preferences, passed to Ask Mosaic",
    );
    expect(within(context).getByText("Your preferences")).toBeTruthy();
    expect(within(context).getByText("In stock")).toBeTruthy();
  });

  it("contains filter focus, makes the background inert, and restores its trigger", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    const opener = screen.getByRole("button", { name: "Brand" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Filters" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.querySelector(".shop-canvas")?.hasAttribute("inert")).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
    expect(
      within(dialog).getByRole("button", { name: "Category" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(
      within(dialog).getByRole("button", { name: "Brand" })
        .getAttribute("aria-expanded"),
    ).toBe("true");

    const close = within(dialog).getByRole("button", { name: "Close filters" });
    await waitFor(() => expect(document.activeElement).toBe(close));
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );
    close.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(focusable.at(-1));

    fireEvent.click(close);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Filters" })).toBeNull()
    );
    expect(document.querySelector(".shop-canvas")?.hasAttribute("inert")).toBe(false);
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(opener);
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

  it("reopens a settled answer without replaying its presentation queue", async () => {
    renderPage();
    await screen.findByText(catalog.products[0].model);
    const opener = screen.getByRole("button", { name: "Ask Mosaic" });
    fireEvent.click(opener);
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    await screen.findByText("Final recommendation");

    fireEvent.click(
      within(screen.getByRole("complementary", { name: "Ask Mosaic" }))
        .getByRole("button", { name: "Close Ask Mosaic" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reopen Ask Mosaic" }));

    const reopened = screen.getByRole("complementary", { name: "Ask Mosaic" });
    expect(within(reopened).getByText("Final recommendation")).toBeTruthy();
    expect(
      [...within(reopened).getByLabelText("Steps I took")
        .querySelectorAll(".ask-mosaic-stage-summary")]
      .map((card) => card.getAttribute("aria-expanded")),
    ).toEqual(["false", "false", "false", "true"]);
  });

  it("closes only the top cart drawer when Ask Mosaic is still open", async () => {
    render(
      <CommerceProvider>
        <CatalogPage />
        <CommerceDrawer />
      </CommerceProvider>,
    );
    await screen.findByText(catalog.products[0].model);
    fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask Mosaic request" }),
      { target: { value: agentResponse.question } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    const assist = screen.getByRole("complementary", { name: "Ask Mosaic" });
    await within(assist).findByText("Final recommendation");
    fireEvent.click(
      within(assist).getAllByRole("button", { name: /Add to bag/ })[0],
    );
    expect(await screen.findByRole("dialog", { name: /Your bag/ })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /Your bag/ })).toBeNull());
    expect(
      screen.getByRole("complementary", { name: "Ask Mosaic" }),
    ).toBeTruthy();
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
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Ask Mosaic" }),
    );
  });

  it("names the reproduced Lab 1 fault when the target never comes back", async () => {
    // The break-first journey turns on this moment. A participant arrives from
    // the hero chip, sees a page of plausible headphones, and has no way to know
    // the one product the query is about is absent. The callout is what makes
    // the fault legible before the diagnosis is asked for.
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true"
        + "&view=results&mission=typo-recovery",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    expect(
      within(callout).getByRole("heading", {
        name: "Issue reproduced: the Sonora WH-C720 is missing",
      }),
    ).toBeTruthy();
    expect(callout.textContent).toContain("deliberate");
    // The file and the task come from the mission manifest, so the callout and
    // the lab guide cannot drift apart.
    expect(callout.textContent).toContain(lab1.participant_edit!.file);
    expect(callout.textContent).toContain(lab1.participant_edit!.task);

    const codeEditor = within(callout).getByRole("link", { name: "Code Editor" });
    expect(codeEditor.getAttribute("href")).toBe(
      "https://code.mosaic-workshop.example",
    );
    expect(codeEditor.getAttribute("target")).toBe("_blank");
    expect(within(callout).getByRole("button", { name: "Search again" })).toBeTruthy();

    // A callout, not a modal: the results are still on the page behind it.
    expect(screen.queryByRole("dialog", { name: /Lab 1/ })).toBeNull();
    expect(callout.compareDocumentPosition(
      document.querySelector(".shop-products")!,
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("blames the environment, not the participant, when the trigram index is gone", async () => {
    // A missing pg_trgm index and an unrepaired CTE produce the same evidence:
    // the target is absent and no candidate carries a trigram rank. Shop used to
    // grade without reading readiness at all, so it told a participant whose
    // cluster was missing the index that they were looking at Lab 1's own fault
    // and pointed them at the file. That is a lost lab, not a hint.
    vi.mocked(api.readiness).mockResolvedValue({
      ...healthyReadiness,
      status: "blocked",
      database: {
        ...healthyReadiness.database,
        missing_retrieval_indexes: ["product_document_trigram_gin_idx"],
      },
    });
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true"
        + "&view=results&mission=typo-recovery",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    await waitFor(() =>
      expect(
        within(callout).getByRole("heading", {
          name: "This is an environment problem, not the lab's fault",
        }),
      ).toBeTruthy()
    );
    expect(callout.textContent).toContain("product_document_trigram_gin_idx");
    // Not the lab's fault, and not the lab's file either.
    expect(callout.textContent).not.toContain("deliberate");
    expect(callout.textContent).not.toContain(lab1.participant_edit!.file);
    expect(callout.textContent).not.toContain(lab1.participant_edit!.task);
    expect(callout.className).toContain("unhealthy");
    // Re-applying the schema happens in another window, exactly as a repair
    // does, so the way back to a live answer stays on the callout.
    expect(within(callout).getByRole("button", { name: "Search again" })).toBeTruthy();
  });

  it("keeps naming the lab's own fault when readiness reports a healthy cluster", async () => {
    // The falsifier for the test above: with every index present, the same
    // response is the defect the participant was sent to find.
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    await waitFor(() => expect(vi.mocked(api.readiness)).toHaveBeenCalled());
    expect(callout.textContent).toContain("deliberate");
    expect(callout.textContent).not.toContain("environment problem");
  });

  it("lands a lab arrival on the callout, not one line under it", async () => {
    // `?view=results` scrolls the results header to the top of the window, which
    // put the callout just above the fold: the participant arrived at a page of
    // plausible headphones with the sentence explaining them off screen.
    const scrolled: Element[] = [];
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: function scrollIntoView(this: Element) {
        scrolled.push(this);
      },
    });
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true"
        + "&view=results&mission=typo-recovery",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    await waitFor(() => expect(scrolled).toContain(callout));
  });

  it("re-runs the same request when the participant searches again", async () => {
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    expect(vi.mocked(api.search)).toHaveBeenCalledTimes(1);

    // The repair happens in another window, so the button has to re-ask Aurora
    // rather than re-render what the browser is already holding.
    vi.mocked(api.search).mockResolvedValue(lab1Search(true));
    fireEvent.click(within(callout).getByRole("button", { name: "Search again" }));

    await waitFor(() => expect(vi.mocked(api.search)).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.search).mock.calls[1][0]).toBe(lab1.query);
    expect(vi.mocked(api.search).mock.calls[1][1]).toMatchObject({
      domain: "consumer_electronics",
      max_price_cents: 20000,
      in_stock_only: true,
    });
    await screen.findByRole("heading", { name: "Repair verified" });
  });

  it("promotes the Playground link out of the disclosure once the repair holds", async () => {
    vi.mocked(api.search).mockResolvedValue(lab1Search(true));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    expect(
      within(callout).getByRole("heading", { name: "Repair verified" }),
    ).toBeTruthy();
    expect(within(callout).queryByRole("button", { name: "Search again" })).toBeNull();

    // Exactly one link, not one in the callout and a second still buried in the
    // collapsed disclosure.
    const playground = screen.getAllByRole("link", {
      name: /See how this was retrieved in the Playground/,
    });
    expect(playground).toHaveLength(1);
    expect(callout.contains(playground[0])).toBe(true);
    expect(playground[0].getAttribute("href")).toContain("/labs/retrieval?");
  });

  it("stays silent for a run the lab does not describe", async () => {
    // Same words, wider gates: a different pool, and a verdict about Lab 1 would
    // be a verdict on a request Lab 1 never made.
    vi.mocked(api.search).mockResolvedValue({
      ...lab1Search(false),
      applied_filters: { domain: "consumer_electronics" },
    });
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}&domain=consumer_electronics`,
    );
    renderPage();

    // The run landed: the receipt disclosure only renders once a response is
    // held. What is absent is any verdict about Lab 1 over the top of it.
    await screen.findByText("Why these results, in this order");
    expect(screen.queryByRole("region", { name: "Lab 1 outcome" })).toBeNull();
  });

  it("offers no Code Editor button when the service publishes no URL", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ...healthFixture,
      code_editor_url: null,
    });
    vi.mocked(api.search).mockResolvedValue(lab1Search(false));
    window.history.replaceState(
      {},
      "",
      `/catalog?q=${encodeURIComponent(lab1.query)}`
        + "&domain=consumer_electronics&max_price_cents=20000&in_stock_only=true",
    );
    renderPage();

    const callout = await screen.findByRole("region", { name: "Lab 1 outcome" });
    expect(within(callout).queryByRole("link", { name: "Code Editor" })).toBeNull();
    // The rest of the callout still stands: the fault and the file to edit are
    // what the participant needs, and the Code Editor is one way to reach it.
    expect(callout.textContent).toContain(lab1.participant_edit!.file);
  });
});
