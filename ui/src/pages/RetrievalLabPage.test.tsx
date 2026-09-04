// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api";
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
    excluded_agent_contract_query_ids: ["G-021"],
    per_query_metrics: [],
  },
  regression_anchors: {
    passed: 4,
    total: 4,
    anchors: [],
    verified_for_running_revision: true,
  },
  eligibility_contracts: {
    fixture_count: 18,
    held: true,
    description: "fixture description",
    fixture_query_ids: [],
  },
  agent_contracts: { guarantees: [] },
  stage_ablation: {
    attributed: false,
    attribution_note: "Metrics pending evaluation for this retrieval revision: fixture.",
    measured_at: "2026-08-23T21:53:32.664198Z",
    spread_note: "fixture spread note",
    scored_query_count: 20,
    arms: [],
    candidate_recall_ceiling: {
      pool_recall_ceiling: 0,
      judged_relevant_never_fetched: 0,
      description: "fixture description",
    },
    per_query: [],
  },
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
    // The lab rail reads where each lab stands, in both places a lab can be
    // broken. Its own coverage is in LabRail.test.tsx.
    labsState: vi.fn(),
    // Stage 03 runs the agent, but only when the participant presses its button.
    agentStream: vi.fn(),
    evidence: vi.fn(),
    toolContracts: vi.fn(),
    retrievalEvent: vi.fn(),
    // The arrival path reads the carried Shop run back as the response it
    // served, which is what fills stages 01 and 02 with its rows.
    retrievalEventResponse: vi.fn(),
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
    projector,
    response,
  }: {
    example?: { id: string };
    loading: boolean;
    projector?: boolean;
    response: SearchResponse | null;
  }) => (
    <section aria-label="Retrieval Observatory">
      <p>observatory projector: {String(Boolean(projector))}</p>
      <p>observatory scenario: {example?.id}</p>
      <p>observatory run: {response ? response.search_event_id : "none"}</p>
      <p>
        observatory rows:{" "}
        {response ? response.results.map((product) => product.title).join(" | ") : "none"}
      </p>
      <p>observatory loading: {String(loading)}</p>
    </section>
  ),
}));

/**
 * The repair panel has its own file. What this page owes it is two ids, so the
 * mock reports the two it was handed and nothing else.
 */
vi.mock("../components/RepairEvidence", () => ({
  RepairEvidence: ({
    baselineSearchEventId,
    latestSearchEventId,
  }: {
    baselineSearchEventId: string | null;
    latestSearchEventId: string | null;
  }) => (
    <section aria-label="Repair evidence">
      <p>repair baseline: {baselineSearchEventId ?? "none"}</p>
      <p>repair latest: {latestSearchEventId ?? "none"}</p>
    </section>
  ),
}));

/** The two elements the lab rail's beats scroll to. */
const SCROLL_MARGIN_SELECTORS = [".labs-stage-copy h2", ".labs-repair h3"];

// Resolved off this file rather than off the working directory, and not with
// `new URL(..., import.meta.url)`: Vite rewrites that exact pattern into an
// asset URL, which is not a path anything can read here.
const SURFACES_CSS = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../surfaces.css"),
  "utf8",
).replaceAll(/\/\*[\s\S]*?\*\//g, "");

/**
 * Every declaration this stylesheet makes for one exact selector, whitespace
 * collapsed. A source read rather than a computed style: jsdom parses no
 * stylesheet this page imports, so `getComputedStyle` here would report the
 * initial value whether or not the rule exists.
 */
function surfacesDeclarationsFor(selector: string): string {
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  const blocks: string[] = [];
  for (let match = rule.exec(SURFACES_CSS); match; match = rule.exec(SURFACES_CSS)) {
    const selectors = match[1].split(",").map((one) => one.replaceAll(/\s+/g, " ").trim());
    if (selectors.includes(selector)) blocks.push(match[2]);
  }
  return blocks.join(" ").replaceAll(/\s+/g, " ").trim();
}

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
  appliedFilters: SearchResponse["applied_filters"] = {},
): SearchResponse {
  return {
    search_event_id: searchEventId,
    query,
    normalized_query: query,
    applied_filters: appliedFilters,
    results,
    diagnostics: null,
  };
}

const firstExample = mosaicRetrievalExamples[0];

// Answered under the scenario's own gates, the way the service echoes them, so
// the page can tell a run of this scenario from a run that merely reused its words.
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
  { ...firstExample.filters },
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
 * Shaped like the real MCP projection: search, evidence, and inspection.
 * Inspection shares the `explain_retrieval` capability with the skill
 * surface's own `explain_retrieval` wire name; MCP does not expose comparison.
 */
const mcpToolContracts: ToolContract[] = [
  {
    name: "search_products",
    capability: "open_retrieval",
    tool_version: "1.0",
    description: "Run the canonical retrieval pipeline through MCP.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
  {
    name: "get_product_evidence",
    capability: "get_product_evidence",
    tool_version: "1.0",
    description: "Read granted product evidence through MCP.",
    input_schema: {},
    output_schema: {},
    read_only: true,
  },
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

/** The event id Shop persisted for the run a participant is looking at. */
const SHOP_EVENT_ID = "9614ed9b-4ceb-4aad-9276-4e69af2231b9";

/**
 * What `GET /api/retrieval/events/{id}/response` serves for that run: the rows
 * Shop was shown, in the order it showed them, rebuilt from the receipt.
 *
 * `embedding_dimensions` is null and `coverage` is absent because neither is
 * persisted, so a replay has nothing to report for them.
 */
const shopResponse: SearchResponse = {
  search_event_id: SHOP_EVENT_ID,
  query: "noice cancelng hedfones",
  normalized_query: "noice cancelng hedfones",
  applied_filters: {},
  results: [
    productWithSignals(2, {
      fts: { rank: 1, raw_score: 1, rrf_contribution: 0.01639 },
      trigram: { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: null, raw_score: null, rrf_contribution: null },
      rrf_score: 0.01639,
      pre_rerank_rank: 7,
      pre_rerank_score: 0.01639,
      rerank_score: 0.41,
      final_rank: 1,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
    productWithSignals(3, {
      fts: { rank: null, raw_score: null, rrf_contribution: null },
      trigram: { rank: null, raw_score: null, rrf_contribution: null },
      semantic: { rank: 2, raw_score: 0.71, rrf_contribution: 0.01587 },
      rrf_score: 0.01587,
      pre_rerank_rank: 9,
      pre_rerank_score: 0.01587,
      rerank_score: 0.38,
      final_rank: 2,
      score_semantics: "rank_fusion_then_bounded_rerank",
    }),
  ],
  diagnostics: {
    strategy: "rrf_fusion+rerank+exact_sku_preservation",
    embedding_model_id: "us.cohere.embed-v4:0",
    embedding_dimensions: null,
    rerank_model_id: "cohere.rerank-v3-5:0",
    rerank_status: "applied",
    retrieval_profile: {} as RetrievalDiagnostics["retrieval_profile"],
    candidate_counts: {
      fused_pool: 50,
      fts_in_pool: 1,
      trigram_in_pool: 0,
      semantic_in_pool: 49,
    },
    stage_timings_ms: {},
    total_latency_ms: 785,
  },
  coverage: null,
};

describe("RetrievalLabPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/labs/retrieval");
    window.localStorage.clear();
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockResolvedValue(primaryResponse);
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.readiness).mockRejectedValue(new Error("readiness unavailable"));
    vi.mocked(api.labsState).mockReset();
    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        {
          lab_id: 1,
          source_state: "broken",
          database_state: "applied",
          detail: "The trigram CTE is absent from the applied function.",
        },
      ],
    });
    vi.mocked(api.retrievalEvent).mockReset();
    vi.mocked(api.retrievalEventResponse).mockReset();
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
      screen.getByText(
        "A search can return a plausible top result while the system behind it is wrong.",
      ),
    ).toBeTruthy();
    // Internal routes only; the strip also carries an outbound GitHub link.
    // Two destinations, not three. Catalog studio runs no retrieval and grades
    // nothing, so it is not a lens on this surface; its own route and the footer
    // link to it both stay.
    expect(
      within(strip)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
        .filter((href) => href?.startsWith("/")),
    ).toEqual(["/labs/retrieval", "/mosaic-labs/hnsw"]);
    expect(
      within(strip)
        .getByRole("link", { name: "Playground" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(within(strip).queryByRole("link", { name: "Catalog studio" })).toBeNull();
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
    expect((query as HTMLInputElement).value).toContain("hedfones");
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

  it("preserves factual baseline and latest run measures after a second pipeline run", async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse);
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("observatory run: first-retrieval-run");
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("Baseline and latest run")).toBeTruthy();
    const baselineRun = screen.getByLabelText("Baseline metrics");
    const latestRun = screen.getByLabelText("Latest run metrics");
    expect(within(baselineRun).getByText("#7")).toBeTruthy();
    expect(within(baselineRun).getByText("#6")).toBeTruthy();
    expect(within(baselineRun).getByText("0")).toBeTruthy();
    expect(within(latestRun).getAllByText("#1")).toHaveLength(2);
    expect(within(latestRun).getByText("4")).toBeTruthy();
    // The two surfaces that name a "before" name the same run.
    expect(screen.getByText("repair baseline: first-retrieval-run")).toBeTruthy();
    expect(document.querySelector(".labs-run-summary")?.textContent)
      .toContain("Baseline first-re");
  });

  it("re-anchors the comparison on the run the participant re-pinned", async () => {
    // The measures and the pinned id are one claim: re-pinning has to move both,
    // or the panel keeps comparing against a run the summary line no longer
    // names as the baseline.
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse)
      .mockResolvedValueOnce(firstComparisonResponse);
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("observatory run: first-retrieval-run");
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("observatory run: latest-retrieval-run");

    fireEvent.click(screen.getByRole("button", { name: "Pin as baseline" }));
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    await screen.findByText("observatory run: first-retrieval-run");
    expect(await screen.findByText("repair baseline: latest-retrieval-run")).toBeTruthy();
    // The baseline column now reports the re-pinned run's own measures.
    const baselineRun = screen.getByLabelText("Baseline metrics");
    expect(within(baselineRun).getAllByText("#1")).toHaveLength(2);
    expect(within(baselineRun).getByText("4")).toBeTruthy();
  });

  it("promotes Package as the conclusion to the four numbered stages", async () => {
    mockPackageRegistry();
    const { container } = render(<RetrievalLabPage />);

    await awaitPackageFinale();
    const finale = container.querySelector(".labs-package-finale");
    const heading = screen.getByRole("heading", { name: "Package what you built" });
    const header = heading.closest(".labs-package-heading");

    expect(finale).toBeTruthy();
    expect(header).toBeTruthy();
    expect(header?.firstElementChild).toBe(heading);
    expect(heading.nextElementSibling?.textContent).toBe(
      "The three labs become one portable retrieval capability with Aurora as its evidence authority.",
    );
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
    expect(await screen.findAllByText("catalog read-only")).toHaveLength(4);
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
    expect(
      await screen.findByText("skills/mosaic-hybrid-retrieval/"),
    ).toBeTruthy();
    expect(
      await screen.findByText(/replace Mosaic's schema, language, models/i),
    ).toBeTruthy();
  });

  it("reports each implemented adapter's real operation count", async () => {
    mockPackageRegistry();
    render(<RetrievalLabPage />);

    await awaitPackageFinale();

    const http = await screen.findByTestId("adapter-http");
    const mcp = await screen.findByTestId("adapter-mcp");
    expect(http.textContent).toMatch(/implemented/i);
    expect(http.textContent).toMatch(/4 operations/i);
    expect(mcp.textContent).toMatch(/implemented/i);
    expect(mcp.textContent).toMatch(/3 operations/i);
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

  it("reads the run Shop served rather than running the query again", async () => {
    // Re-running the query minted a second event, so the run behind the results
    // the shopper was looking at became unreachable the moment they followed the
    // link. Nothing downstream could then compare against what Shop served.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    await waitFor(() => {
      expect(api.retrievalEventResponse).toHaveBeenCalledWith(SHOP_EVENT_ID);
    });
    expect(api.search).not.toHaveBeenCalled();
    expect(screen.getByText("This is the exact run from Shop")).toBeTruthy();
    // The banner names the run it read, so the claim is checkable rather than
    // decorative.
    expect(document.querySelector(".labs-carried-over")?.textContent)
      .toContain(SHOP_EVENT_ID.slice(0, 8));
  });

  it("fills the stages with the rows Shop served, in the order it served them", async () => {
    // The stages sat dormant behind the banner: the surface said "this is the
    // exact run from Shop" over an empty Retrieve stage, so the participant had
    // to press Run to see anything -- which mints the second event the hand-off
    // exists to avoid.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    // Stage 02 receives the served rows, titles and order intact.
    expect(await screen.findByText(`observatory run: ${SHOP_EVENT_ID}`)).toBeTruthy();
    expect(
      screen.getByText("observatory rows: Mosaic Sonora WH-C720 | Mosaic Northstar Space Q45"),
    ).toBeTruthy();
    // Stage 01 reports the pool the receipt recorded, not a fresh one.
    const figures = screen.getByLabelText("Retrieval figures");
    expect(
      within(figures).getByText("Candidate pool").closest(".labs-figure")?.textContent,
    ).toContain("50");
    expect(
      within(figures).getByText("Rows returned").closest(".labs-figure")?.textContent,
    ).toContain("2");
    // And Stage 02's receipt reports the run's own latency, which only a
    // persisted run can supply here.
    expect(
      screen.getByLabelText("End-to-end retrieval receipt").textContent,
    ).toContain("785 ms");
    expect(screen.queryByText(/Run the pipeline to fill each step/)).toBeNull();
    expect(api.search).not.toHaveBeenCalled();
    // The receipt route is the arrival's only read now: the run replay carries
    // no product rows, so calling it here would be a second request for less.
    expect(api.retrievalEvent).not.toHaveBeenCalled();
  });

  it("still delivers the carried run when React mounts the page twice", async () => {
    // `main.tsx` wraps the app in StrictMode, so a development mount runs
    // setup, cleanup, setup. The arrival effect guarded its own resolution with
    // a closure flag that the first cleanup flipped, while the ref that stops a
    // second fetch made the second setup return early: the carried run then
    // landed nowhere, and nothing replayed the query either.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />, { wrapper: StrictMode });

    expect(await screen.findByText(`repair baseline: ${SHOP_EVENT_ID}`)).toBeTruthy();
    expect(screen.getByText("This is the exact run from Shop")).toBeTruthy();
    // Still exactly one read, and still no replay: the double mount must not
    // spend a second request either.
    expect(vi.mocked(api.retrievalEventResponse)).toHaveBeenCalledTimes(1);
    expect(api.search).not.toHaveBeenCalled();
  });

  it("pins the carried-over run as the baseline the repair panel compares from", async () => {
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    expect(await screen.findByText(`repair baseline: ${SHOP_EVENT_ID}`)).toBeTruthy();
    expect(screen.getByText(`repair latest: ${SHOP_EVENT_ID}`)).toBeTruthy();
  });

  it("keeps one before-anchor after a carried arrival, rather than two", async () => {
    // The pinned id was the Shop run while the measures came from the first
    // Playground run, so the run summary, the repair panel, and the run
    // comparison named two different "before" runs on one screen.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    vi.mocked(api.search).mockResolvedValue(latestComparisonResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);
    await screen.findByText(`repair baseline: ${SHOP_EVENT_ID}`);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("repair latest: latest-retrieval-run")).toBeTruthy();
    // Still the Shop run, and now measurable: the carried arrival pinned the
    // response it served, so "before" is that run rather than the first
    // Playground run standing in for it.
    expect(screen.getByText(`repair baseline: ${SHOP_EVENT_ID}`)).toBeTruthy();
    expect(screen.getByText("Baseline and latest run")).toBeTruthy();
    const before = screen.getByLabelText("Baseline metrics");
    const after = screen.getByLabelText("Latest run metrics");
    // The Shop run's own numbers: rank 7 in the fused pool, no close-spelling
    // candidates. The Playground run that followed reports its own. Read cell by
    // cell rather than off the section's text: `toContain("0")` matches the "0"
    // inside "20" or a run id, so a wrong figure could still pass.
    expect(within(before).getByText("#7")).toBeTruthy();
    expect(within(before).getByText("0")).toBeTruthy();
    expect(within(after).getAllByText("#1")).toHaveLength(2);
    expect(within(after).getByText("4")).toBeTruthy();
  });

  it("names the fault when the Shop run could not be read for another reason", async () => {
    // A 503 reported as "could not be found" sends the participant looking for a
    // missing run rather than at an API that is not answering.
    vi.mocked(api.retrievalEventResponse).mockRejectedValue(
      new ApiError(503, "Service unavailable"),
    );
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    expect(
      await screen.findByText(/The Shop run could not be read \(503\), so the query was run again/),
    ).toBeTruthy();
    expect(screen.queryByText(/could not be found/)).toBeNull();
    await waitFor(() => expect(api.search).toHaveBeenCalled());
  });

  it("runs the query again, and says so, when the Shop run cannot be read back", async () => {
    vi.mocked(api.retrievalEventResponse).mockRejectedValue(
      new ApiError(404, "Search event not found"),
    );
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        "noice cancelng hedfones",
        {},
        { limit: 12, rerank: true },
      );
    });
    expect(
      await screen.findByText(/The Shop run could not be found, so the query was run again/),
    ).toBeTruthy();
  });

  it("still replays a hand-off that carries no event", async () => {
    window.history.replaceState({}, "", "/labs/retrieval?q=noice+cancelng+hedfones");
    render(<RetrievalLabPage />);

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith(
        "noice cancelng hedfones",
        {},
        { limit: 12, rerank: true },
      );
    });
    expect(api.retrievalEventResponse).not.toHaveBeenCalled();
    expect(screen.getByText("Carried over from Shop")).toBeTruthy();
  });

  it("pins the first run as the baseline and keeps it while later runs land", async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse);
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    expect(await screen.findByText("repair baseline: first-retrieval-run")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("repair latest: latest-retrieval-run")).toBeTruthy();
    expect(screen.getByText("repair baseline: first-retrieval-run")).toBeTruthy();
  });

  it("re-pins the baseline to the run on screen when asked", async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce(firstComparisonResponse)
      .mockResolvedValueOnce(latestComparisonResponse);
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("repair baseline: first-retrieval-run");
    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("repair latest: latest-retrieval-run");

    fireEvent.click(screen.getByRole("button", { name: "Pin as baseline" }));

    expect(await screen.findByText("repair baseline: latest-retrieval-run")).toBeTruthy();
  });

  it("drops the pinned baseline when another scenario is selected", async () => {
    render(<RetrievalLabPage />);

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await screen.findByText("repair baseline: retrieval-primary");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "exact-identity" } });

    expect(await screen.findByText("repair baseline: none")).toBeTruthy();
    expect(screen.getByText("repair latest: none")).toBeTruthy();
  });

  it("keeps the scenario's verdict off a carried run that used other gates", async () => {
    // The scenario constrains a domain, a price ceiling and stock. Shop's run
    // applied none of them, so it retrieved a wider pool than the scenario
    // describes and its rows cannot answer the scenario's question either way.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    expect(await screen.findByText("Shop run loaded")).toBeTruthy();
    expect(
      screen.getByText(/The lab verdict applies to the scenario's own filters/),
    ).toBeTruthy();
    expect(screen.queryByText("Issue reproduced")).toBeNull();
    expect(screen.queryByText("Repair verified")).toBeNull();
  });

  it("stops calling a Playground run the run Shop served", async () => {
    // The hand-off flag survived the arrival, so the first press of Run pipeline
    // minted a new event and the banner still said "Shop run loaded" over it,
    // with a detail claiming these were the rows Shop was shown. They are not:
    // this run happened here, seconds ago.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    vi.mocked(api.search).mockResolvedValue(
      responseFor("playground-run-after-arrival", shopResponse.query, shopResponse.results),
    );
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);
    expect(await screen.findByText("Shop run loaded")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("Live run complete")).toBeTruthy();
    expect(screen.queryByText("Shop run loaded")).toBeNull();
    expect(
      screen.queryByText(/These rows are the run Shop served/),
    ).toBeNull();
    // And the neutral detail names what actually diverged. `Run pipeline` re-ran
    // the carried request, so this run asked the scenario's own question under
    // Shop's gates: "this query is outside the selected checkpoint" was false of
    // it, and pointed at the half that had not diverged.
    expect(
      screen.getByText(/This run used Shop's gates, so the lab verdict does not apply/),
    ).toBeTruthy();
    expect(screen.queryByText(/outside the selected checkpoint/)).toBeNull();
  });

  it("names the Shop run as the baseline once a fresh run replaces it", async () => {
    // The strip was keyed on the arrival rather than on the run on screen, so
    // after Run pipeline it still said "This is the exact run from Shop ...
    // Nothing was re-run" over a run minted here seconds ago. The hand-off is
    // still true, so the strip stays -- it just has to say which run is which.
    vi.mocked(api.retrievalEventResponse).mockResolvedValue(shopResponse);
    vi.mocked(api.search).mockResolvedValue(
      responseFor("playground-run-after-arrival", shopResponse.query, shopResponse.results),
    );
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);
    expect(await screen.findByText("This is the exact run from Shop")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run pipeline" }));

    expect(await screen.findByText("Carried over from Shop")).toBeTruthy();
    expect(screen.queryByText("This is the exact run from Shop")).toBeNull();
    const strip = document.querySelector(".labs-carried-over");
    expect(strip?.textContent).toContain(
      `Baseline: the Shop run ${SHOP_EVENT_ID.slice(0, 8)}. Latest: a new run of the same query and gates.`,
    );
    expect(strip?.textContent).not.toContain("Nothing was re-run");
  });

  it("judges the scenario when the carried run used the scenario's own gates", async () => {
    vi.mocked(api.retrievalEventResponse).mockResolvedValue({
      ...shopResponse,
      applied_filters: { ...firstExample.filters },
    });
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    // The Shop run carries no trigram rank on the target, which is the defect
    // Lab 1 exists to show, so the verdict is the scenario's own.
    expect(await screen.findByText("Issue reproduced")).toBeTruthy();
    expect(screen.getByText("Fuzzy retrieval is still disconnected")).toBeTruthy();
    expect(screen.queryByText("Shop run loaded")).toBeNull();
  });

  it("reports the carried run as in flight rather than as an empty stage", async () => {
    // Stage 02 rendered its "no run yet" panel under a banner announcing the
    // exact run from Shop, for as long as the read took.
    let resolveArrival: (response: SearchResponse) => void = () => {};
    vi.mocked(api.retrievalEventResponse).mockImplementation(
      () => new Promise<SearchResponse>((resolve) => {
        resolveArrival = resolve;
      }),
    );
    window.history.replaceState(
      {},
      "",
      `/labs/retrieval?q=noice+cancelng+hedfones&event=${SHOP_EVENT_ID}`,
    );
    render(<RetrievalLabPage />);

    expect(await screen.findByText("observatory loading: true")).toBeTruthy();
    expect(screen.getByText("observatory run: none")).toBeTruthy();

    resolveArrival(shopResponse);

    expect(await screen.findByText(`observatory run: ${SHOP_EVENT_ID}`)).toBeTruthy();
    expect(screen.getByText("observatory loading: false")).toBeTruthy();
  });

  it("says which lab this is, and what it is waiting on, above the stages", async () => {
    // Four numbered stages describe the pipeline, not the session. Nothing on
    // screen used to name the lab the participant was in or the file they were
    // there to edit, so the rail carries both, above the first stage.
    const { container } = render(<RetrievalLabPage />);

    const rail = screen.getByRole("navigation", { name: "Lab rail" });
    const strip = screen.getByLabelText("Environment readiness");
    const firstStage = container.querySelector(".labs-stage")!;

    expect(rail.compareDocumentPosition(firstStage))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(strip.compareDocumentPosition(firstStage))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(rail).getByText(mosaicRetrievalExamples[0].title)).toBeTruthy();
    // The beats are in-page anchors, so each one has to land somewhere. Two of
    // the three targets are this page's own stage headings; the third belongs to
    // RepairEvidence, whose own suite pins it.
    for (const beat of ["Observe", "Prove"]) {
      const href = within(rail).getByRole("link", { name: beat }).getAttribute("href")!;
      expect(container.querySelector(href)).toBeTruthy();
    }
    expect(await within(rail).findByText("source: broken")).toBeTruthy();
    // The readiness read is rejected in this suite, so no row may claim a value.
    expect(within(strip).getAllByText("not checked").length).toBe(9);
  });

  it("holds every beat's target clear of the sticky chrome above it", () => {
    // The rail is sticky under a sticky site header, so a browser that scrolls
    // a beat's target to the top of the viewport parks it underneath both and
    // the click reads as having gone nowhere. jsdom does no layout and computes
    // no cascade, so what can be checked here is that the rule exists and that
    // the elements the beats actually land on are the ones it selects.
    const { container } = render(<RetrievalLabPage />);
    const rail = screen.getByRole("navigation", { name: "Lab rail" });

    for (const beat of ["Observe", "Prove"]) {
      const href = within(rail).getByRole("link", { name: beat }).getAttribute("href")!;
      // RepairEvidence is mocked in this file, so its heading is not here to
      // check; `RepairEvidence.test.tsx` pins the id it carries.
      expect(container.querySelector(href)!.matches(SCROLL_MARGIN_SELECTORS.join(","))).toBe(true);
    }

    for (const selector of SCROLL_MARGIN_SELECTORS) {
      expect(surfacesDeclarationsFor(selector)).toContain(
        "scroll-margin-top: calc( var(--topbar-height) + var(--labs-rail-height, 0px) + 18px );",
      );
    }
    // The witness that the search above discriminates: a rule in the same file
    // that must not carry the offset, and would report one if this were reading
    // the whole stylesheet rather than the two blocks it names.
    expect(surfacesDeclarationsFor(".labs-rail-lab")).not.toContain("scroll-margin-top");
    expect(surfacesDeclarationsFor(".labs-rail-lab")).toContain("display: grid;");
  });

  it("moves the rail to the lab the deep link selected", () => {
    window.history.replaceState({}, "", "/labs/retrieval?example=rank-with-evidence");
    render(<RetrievalLabPage />);

    const rail = screen.getByRole("navigation", { name: "Lab rail" });
    const lab = mosaicRetrievalExamples.find(
      (example) => example.id === "rank-with-evidence",
    )!;
    expect(within(rail).getByText(lab.title)).toBeTruthy();
    expect(within(rail).getByText(lab.participant_edit!.file)).toBeTruthy();
  });

  it("switches the surface to projector mode and remembers the choice", () => {
    const { container } = render(<RetrievalLabPage />);
    const page = container.querySelector(".lab-page")!;
    const toggle = screen.getByRole("button", { name: "Projector mode" });

    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(page.getAttribute("data-projector")).toBeNull();
    expect(screen.getByText("observatory projector: false")).toBeTruthy();

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(page.getAttribute("data-projector")).toBe("true");
    expect(screen.getByText("observatory projector: true")).toBeTruthy();
    expect(window.localStorage.getItem("mosaic.projector")).toBe("true");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(page.getAttribute("data-projector")).toBeNull();
    expect(window.localStorage.getItem("mosaic.projector")).toBe("false");
  });

  it("opens in projector mode when the room already chose it", () => {
    // A facilitator sets this once and reloads through the session. Losing it on
    // every navigation is what made it useless the first time it was tried.
    window.localStorage.setItem("mosaic.projector", "true");
    const { container } = render(<RetrievalLabPage />);

    expect(container.querySelector(".lab-page")?.getAttribute("data-projector"))
      .toBe("true");
    expect(
      screen.getByRole("button", { name: "Projector mode" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("still renders when storage refuses to answer", () => {
    // Safari in private browsing throws on both read and write. A preference is
    // not worth a blank Playground.
    const denied = () => {
      throw new Error("storage denied");
    };
    vi.spyOn(window.localStorage.__proto__, "getItem").mockImplementation(denied);
    vi.spyOn(window.localStorage.__proto__, "setItem").mockImplementation(denied);
    const { container } = render(<RetrievalLabPage />);

    const toggle = screen.getByRole("button", { name: "Projector mode" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector(".lab-page")?.getAttribute("data-projector"))
      .toBe("true");
    vi.restoreAllMocks();
  });
});
