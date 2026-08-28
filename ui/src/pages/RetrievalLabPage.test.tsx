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
import { showcaseCatalogPage } from "../showcase";
import type {
  ProductSummary,
  ReadinessResponse,
  RetrievalDiagnostics,
  RetrievalScorecardResponse,
  SearchResponse,
  ToolContract,
} from "../types";
import { RetrievalLabPage } from "./RetrievalLabPage";

/**
 * Just enough of `GET /api/scorecard` for Stage 04 to mount without an
 * unmocked-fetch crash. `RetrievalScorecard.test.tsx` owns the real
 * provenance-gating coverage; this file only needs the page as a whole to
 * render.
 */
const minimalScorecard: RetrievalScorecardResponse = {
  provenance: {
    measured_at: "2026-08-23T21:53:32.664198Z",
    query_set: "data/evals/canonical_queries.jsonl",
    query_set_sha256: "a".repeat(64),
    scored_query_set_sha256: "b".repeat(64),
    ranked_result_sha256: "c".repeat(64),
    dataset_manifest_sha256: "d".repeat(64),
    models: { embedding: "us.cohere.embed-v4:0", rerank: "cohere.rerank-v3-5:0" },
    aurora_configuration: {},
    hnsw_settings: {},
    retrieval_profile: {},
    database_instance_id: "test-instance",
    strategy: "rrf_fusion+rerank+exact_sku_preservation",
    source_revision: "0".repeat(40),
    source_worktree_dirty: false,
    current_source_revision: "1".repeat(40),
    current_source_worktree_dirty: false,
    attributed: false,
    attribution_note: "Metrics pending evaluation for this retrieval revision: fixture.",
  },
  retrieval_quality: {
    sample_size: 19,
    canonical_query_count: 20,
    sample_description: "fixture sample",
    recall_at_10: 0.82,
    mrr: 0.92,
    ndcg_at_10: 0.85,
    metric_explanations: { "recall@10": "x", mrr: "y", "ndcg@10": "z" },
    excluded_agent_contract_query_ids: ["G-010"],
    per_query_metrics: [],
  },
  regression_anchors: { passed: 4, total: 4, anchors: [] },
  eligibility_contracts: {
    fixture_count: 18,
    held: true,
    description: "fixture description",
    fixture_query_ids: [],
  },
  agent_contracts: { guarantees: [] },
};

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  api: {
    search: vi.fn(),
    // Stage 01 reads index health on mount, so it can tell "pg_trgm is installed
    // and its index is valid" apart from "pg_trgm contributed nothing".
    readiness: vi.fn(),
    // Stage 03 runs the agent, but only when the participant presses its button.
    agentStream: vi.fn(),
    evidence: vi.fn(),
    toolContracts: vi.fn(),
    retrievalEvent: vi.fn(),
    retrievalPlan: vi.fn(),
    // Stage 04 (Prove) loads the scorecard on mount. Its own tests live in
    // RetrievalScorecard.test.tsx; a resolved default here just keeps every
    // other test in this file from tripping over an unmocked fetch.
    scorecard: vi.fn(),
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
primaryResponse.diagnostics = {
  strategy: "hybrid",
  embedding_model_id: "us.cohere.embed-v4:0",
  embedding_dimensions: 1024,
  rerank_model_id: "cohere.rerank-v3-5:0",
  rerank_status: "applied",
  retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
  candidate_counts: { trigram_in_pool: 4 },
  stage_timings_ms: {},
  total_latency_ms: 100,
};

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

/**
 * Shaped like the real `GET /api/tools?surface=skill` projection: four tool
 * names, each carrying its own `capability` (`db/config/agent_tool_contracts.json`
 * declares exactly these four on the skill surface).
 */
const skillToolContracts: ToolContract[] = [
  {
    name: "search_products",
    capability: "open_retrieval",
    tool_version: "1.0",
    description: "Run filtered lexical, fuzzy, semantic, RRF fusion, and bounded reranking.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
  {
    name: "get_product_evidence",
    capability: "get_product_evidence",
    tool_version: "1.0",
    description: "Rank fresh source-addressable specifications and reviews.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
  {
    name: "compare_products",
    capability: "compare_products",
    tool_version: "1.0",
    description: "Compare two to five authorized products.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
  {
    name: "explain_retrieval",
    capability: "explain_retrieval",
    tool_version: "1.0",
    description: "Replay persisted ranking signals for an authorized event.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
];

/**
 * The mcp surface carries `inspect_retrieval_run`, which shares the
 * `explain_retrieval` capability with the skill surface's own `explain_retrieval`
 * tool. The badge only needs a non-empty list, never a name or a capability, so
 * that overlap is irrelevant here.
 */
const mcpToolContracts: ToolContract[] = [
  {
    name: "inspect_retrieval_run",
    capability: "explain_retrieval",
    tool_version: "1.0",
    description: "Replay a persisted retrieval event through the stateless MCP adapter.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
];

function mockPackageRegistry() {
  vi.mocked(api.toolContracts).mockImplementation(async (surface) => {
    if (surface === "skill") return skillToolContracts;
    if (surface === "mcp") return mcpToolContracts;
    return [];
  });
}

/**
 * The Package finale (stage 04, after the scorecard) loads on mount, the
 * same lifecycle the scorecard's own fetch already uses -- there is no
 * disclosure left to open now that packaging is not a click behind stage 03.
 */
async function awaitPackageFinale() {
  await screen.findByText("Package what you built");
}

/** All three retrieval indexes present, valid and ready -- nothing broken. */
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
    agent: "agent",
    synthesis: "synthesis",
  },
  bedrock_credentials: { ready: true },
};

/** A run where every arm found candidates, so none can read as disconnected. */
const allArmsHealthyDiagnostics = {
  strategy: "hybrid",
  embedding_model_id: "us.cohere.embed-v4:0",
  embedding_dimensions: 1024,
  rerank_model_id: "cohere.rerank-v3-5:0",
  rerank_status: "applied" as const,
  retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
  candidate_counts: {
    fused_pool: 12,
    fts_in_pool: 5,
    trigram_in_pool: 4,
    semantic_in_pool: 10,
  },
  stage_timings_ms: {},
  total_latency_ms: 100,
} satisfies NonNullable<SearchResponse["diagnostics"]>;

const allArmsHealthyResponse: SearchResponse = {
  ...primaryResponse,
  search_event_id: "all-arms-healthy",
  diagnostics: allArmsHealthyDiagnostics,
};

describe("RetrievalLabPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/labs/retrieval");
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockResolvedValue(primaryResponse);
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.readiness).mockRejectedValue(new Error("readiness unavailable"));
    vi.mocked(api.scorecard).mockReset();
    vi.mocked(api.scorecard).mockResolvedValue(minimalScorecard);
    // Stage 04's Package finale loads on mount too, same as the scorecard.
    // A resolved default here keeps every test that never calls
    // `mockPackageRegistry()` from tripping the finale's own error branch.
    vi.mocked(api.toolContracts).mockReset();
    vi.mocked(api.toolContracts).mockResolvedValue([]);
  });

  afterEach(cleanup);

  it("is reachable from the other Playground lenses and marks itself current", () => {
    // A documented participant surface that carried no navigation, so the only ways
    // in were a product-page link and a lab-mission deep link.
    render(<RetrievalLabPage />);

    const strip = screen.getByRole("navigation", { name: "Playground lenses" });
    expect(screen.getByRole("heading", { name: "Mosaic Playground" })).toBeTruthy();
    expect(
      screen.getByText("See how retrieval becomes a recommendation."),
    ).toBeTruthy();
    // Internal routes only; the strip also carries an outbound GitHub link.
    expect(
      within(strip)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
        .filter((href) => href?.startsWith("/")),
    ).toEqual(["/labs/retrieval", "/mosaic-labs/hnsw", "/mosaic-labs/studio"]);
    expect(
      within(strip)
        .getByRole("link", { name: "Retrieve, rank, reason" })
        .getAttribute("aria-current"),
    ).toBe("page");
    // No retired name and no "Optional" badge anywhere on the surface.
    expect(strip.textContent).not.toMatch(/Observatory|Optional|Mosaic Labs/);
  });

  it("structures the surface as 01 Retrieve, 02 Rank, 03 Reason, 04 Prove", () => {
    // The workshop model is Retrieve -> Rank -> Reason -> Prove, so the numbers
    // carry information rather than decorating a list. This is the only surface
    // that numbers its sections. Prove is the Retrieval Scorecard: the
    // culmination, not a fourth lab.
    const { container } = render(<RetrievalLabPage />);

    expect(
      [...container.querySelectorAll(".labs-stage-number")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["01", "02", "03", "04"]);
    expect(
      [...container.querySelectorAll(".labs-stage-copy h2")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["Retrieve", "Rank", "Reason", "Prove"]);
  });

  it("bridges each customer word to the PostgreSQL feature behind it", () => {
    // The whole reason this surface exists, so it is above the stages and not
    // behind a disclosure.
    const { container } = render(<RetrievalLabPage />);
    const bridge = container.querySelector(".labs-bridge")!;
    const pairs = [...bridge.querySelectorAll("dl > div")].map((row) => [
      row.querySelector("dt")?.textContent,
      row.querySelector("dd")?.textContent,
    ]);

    expect(pairs).toEqual([
      ["Exact terms", "PostgreSQL Full-Text Search"],
      ["Close spelling", "pg_trgm"],
      ["Meaning match", "pgvector / HNSW"],
    ]);
  });

  it("carries one way to start each of the two things it can run", () => {
    // Two run controls with different verbs, one live and one replaying a fixture,
    // is how this page ended up teaching that the numbers were not measured. There
    // is no fixture replay now: the retrieval pipeline and the agent are two real
    // requests, so they get one button each and the verbs name which is which.
    render(<RetrievalLabPage />);
    const actions = screen
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());
    expect(actions.filter((label) => /^Run|^Replay/.test(label ?? ""))).toEqual([
      "Run pipeline",
      "Run the agent",
    ]);
  });

  it("puts the scenario choice before the action that runs it", () => {
    // The picker used to sit inside the matrix, below the button that consumed it,
    // so the page read run-then-pick. Both controls are now in the masthead in the
    // order they are used.
    const { container } = render(<RetrievalLabPage />);
    const action = container.querySelector(".retrieval-run-action")!;
    const controls = [...action.querySelectorAll("select, input, button")];

    expect(controls[0].tagName).toBe("SELECT");
    expect(controls[1].tagName).toBe("INPUT");
    expect(controls[2].textContent).toContain("Run pipeline");
    // One picker on the page, not one per instrument.
    expect(container.querySelectorAll("select")).toHaveLength(1);
  });

  it("keeps a deliberate typo query under participant control", () => {
    render(<RetrievalLabPage />);

    const query = screen.getByRole("searchbox", { name: "Retrieval query" });
    expect(query.getAttribute("spellcheck")).toBe("false");
    expect(query.getAttribute("autocomplete")).toBe("off");
    expect((query as HTMLInputElement).value).toContain("Sonorra");
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

  it("does not claim an outcome before a live run exists", () => {
    render(<RetrievalLabPage />);

    expect(document.querySelector(".lab-outcome")).toBeNull();
  });

  it("judges the selected checkpoint after its canonical query runs", async () => {
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("Repair verified")).toBeTruthy();
    expect(screen.getByText("Fuzzy retrieval is contributing")).toBeTruthy();
    expect(screen.queryByText(/Canonical query/)).toBeNull();
  });

  it("runs an edited query live without claiming the checkpoint passed", async () => {
    const customQuery = "quiet office keyboard with tactile switches";
    render(<RetrievalLabPage />);

    fireEvent.change(screen.getByRole("searchbox", { name: "Retrieval query" }), {
      target: { value: customQuery },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        customQuery,
        firstExample.filters,
        { limit: 12, rerank: true },
      );
    });
    expect(await screen.findByText("Live run complete")).toBeTruthy();
    expect(screen.queryByText("Repair verified")).toBeNull();
  });

  it("shows every arm's own Postgres index in the ordinary, nothing-broken render", async () => {
    // The gap this closes: `indexName` used to reach the screen only inside
    // `ChannelSplit`, the split rendered solely for a required arm the run did
    // not get. A check that only asserted the text appeared somewhere would
    // already pass today on that broken branch, so this run is deliberately
    // healthy in every arm and asserts the ordinary list carries all three
    // index names while the broken-arm split never renders at all.
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.readiness).mockResolvedValue(healthyReadiness);
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockResolvedValueOnce(allArmsHealthyResponse);

    render(<RetrievalLabPage />);
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    // Witness that the ordinary list actually rendered, independently of the
    // index-name assertion below: a literal row count, not a count derived
    // from the same "does it mention the index name" predicate.
    await waitFor(() => {
      expect(document.querySelectorAll(".labs-channel-list > li")).toHaveLength(3);
    });
    expect(document.querySelector(".labs-channel-split")).toBeNull();

    const items = [...document.querySelectorAll(".labs-channel-list > li")];
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("product_document_fts_gin_idx"),
      expect.stringContaining("product_document_trigram_gin_idx"),
      expect.stringContaining("product_document_embedding_hnsw_cosine_idx"),
    ]);
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
    // Several stages report their own state, so this is scoped to the run control's.
    expect(
      screen
        .getAllByRole("status")
        .map((node) => node.textContent)
        .join(" "),
    ).toContain("Embedding, retrieving, fusing, and reranking.");

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
    expect(screen.getByRole("heading", { name: "Retrieve" })).toBeTruthy();
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

  it("names every skill capability the registry declares", async () => {
    mockPackageRegistry();
    render(<RetrievalLabPage />);

    await awaitPackageFinale();

    // Witness, independent of any text this test reads off the page: the
    // loader actually reached the registry for both adapter surfaces, rather
    // than the assertions below passing because stray markup happened to match.
    await waitFor(() => {
      expect(api.toolContracts).toHaveBeenCalledWith("skill");
      expect(api.toolContracts).toHaveBeenCalledWith("mcp");
    });

    // Singular `findByText`, deliberately: it throws on "multiple elements", so
    // it also pins that no row prints its own name twice. An earlier version of
    // this section rendered `capability` beside `name`, and three of the four
    // skill capabilities are spelled identically to their tool name
    // (`db/config/agent_tool_contracts.json`), so those rows repeated themselves.
    for (const name of [
      "search_products",
      "get_product_evidence",
      "compare_products",
      "explain_retrieval",
    ]) {
      expect(await screen.findByText(name)).toBeTruthy();
    }

    // Each row also carries what the operation does, which is the part another
    // agent needs in order to call it. A literal, not read back off the fixture.
    expect(
      await screen.findByText(/Compare two to five authorized products/i),
    ).toBeTruthy();
  });

  it("labels A2A as documentation rather than available", async () => {
    mockPackageRegistry();
    render(<RetrievalLabPage />);

    await awaitPackageFinale();

    // Witness: the loader ran for both surfaces, independent of the copy this
    // test checks below.
    await waitFor(() => {
      expect(api.toolContracts).toHaveBeenCalledWith("skill");
      expect(api.toolContracts).toHaveBeenCalledWith("mcp");
    });

    const a2a = await screen.findByTestId("adapter-a2a");
    expect(a2a.textContent).toMatch(/documented, not deployed/i);
    expect(a2a.textContent).not.toMatch(/implemented/i);
    expect(a2a.textContent).not.toMatch(/connected|available/i);
    expect(a2a.querySelector("a, button")).toBeNull();

    // Pair the absence with a positive: the two measured adapters *do* say
    // "Implemented", so this section was not simply emptied out.
    expect((await screen.findByTestId("adapter-http")).textContent).toMatch(/implemented/i);
    expect((await screen.findByTestId("adapter-mcp")).textContent).toMatch(/implemented/i);
  });

  it("says retrieval authority does not move", async () => {
    mockPackageRegistry();
    render(<RetrievalLabPage />);

    await awaitPackageFinale();

    // Witness: the loader ran for both surfaces, independent of the closing
    // copy this test checks below.
    await waitFor(() => {
      expect(api.toolContracts).toHaveBeenCalledWith("skill");
      expect(api.toolContracts).toHaveBeenCalledWith("mcp");
    });

    expect(
      await screen.findByText(/retrieval authority stays in Aurora/i),
    ).toBeTruthy();
  });

  it("packages after Prove: Package follows the scorecard inside stage 04, not stage 03", async () => {
    // The bug this guards against is a layout regression, not a missing
    // feature: rendering the finale back inside Reason, or above the
    // scorecard inside Prove, would still leave every "is it present"
    // assertion above green. Only document order catches that, so this test
    // reads `querySelectorAll` on a combined selector -- which the DOM spec
    // returns in tree order regardless of which branch of the selector list
    // matched -- rather than asking "does each exist".
    mockPackageRegistry();
    const { container } = render(<RetrievalLabPage />);

    await awaitPackageFinale();
    await waitFor(() => {
      expect(api.toolContracts).toHaveBeenCalledWith("skill");
      expect(api.toolContracts).toHaveBeenCalledWith("mcp");
    });

    const stages = [...container.querySelectorAll(".labs-stage")];
    const stageNamed = (title: string) =>
      stages.find(
        (stage) => stage.querySelector(".labs-stage-copy h2")?.textContent === title,
      );
    const proveStage = stageNamed("Prove");
    const reasonStage = stageNamed("Reason");
    if (!proveStage || !reasonStage) {
      throw new Error("Expected both a Prove stage and a Reason stage");
    }

    const proveContent = [
      ...proveStage.querySelectorAll(".labs-scorecard, .labs-package-finale"),
    ];
    expect(proveContent.map((node) => node.className)).toEqual([
      "labs-scorecard",
      "labs-package-finale",
    ]);

    // Removed from stage 03 completely, not merely hidden there.
    expect(reasonStage.querySelector(".labs-package-finale")).toBeNull();
    expect(within(reasonStage as HTMLElement).queryByText("Package what you built")).toBeNull();
  });
});
