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
  AgentResponse,
  ProductSummary,
  RetrievalDiagnostics,
  SearchResponse,
  ToolContract,
} from "../types";
import { RetrievalLabPage } from "./RetrievalLabPage";

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
 * The Reason stage needs one completed agent run before its disclosure shelf,
 * including "Package what you built", renders at all.
 */
const packagingAgentResponse: AgentResponse = {
  agent_run_id: "agent-packaging",
  question: "quiet office keyboard",
  answer: "Packaging disclosure smoke run.",
  plan: [],
  recommendations: [],
  citations: [],
  trace: [],
};

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

function mockPackagingDisclosureDependencies() {
  vi.mocked(api.agentStream).mockImplementation(
    async (_question, _filters, onEvent) => {
      onEvent({ type: "complete", response: packagingAgentResponse });
    },
  );
  vi.mocked(api.toolContracts).mockImplementation(async (surface) => {
    if (surface === "skill") return skillToolContracts;
    if (surface === "mcp") return mcpToolContracts;
    return [];
  });
}

/** Runs the agent, then opens the "Package what you built" disclosure. */
async function openPackagingDisclosure() {
  fireEvent.click(screen.getByRole("button", { name: "Run the agent" }));
  const summary = await screen.findByText("Package what you built");
  fireEvent.click(summary);
}

describe("RetrievalLabPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/labs/retrieval");
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockResolvedValue(primaryResponse);
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.readiness).mockRejectedValue(new Error("readiness unavailable"));
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

  it("structures the surface as 01 Retrieve, 02 Rank, 03 Reason", () => {
    // The workshop model is Retrieve -> Rank -> Reason, so the numbers carry
    // information rather than decorating a list. This is the only surface that
    // numbers its sections.
    const { container } = render(<RetrievalLabPage />);

    expect(
      [...container.querySelectorAll(".labs-stage-number")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["01", "02", "03"]);
    expect(
      [...container.querySelectorAll(".labs-stage-copy h2")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["Retrieve", "Rank", "Reason"]);
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
    expect((query as HTMLInputElement).value).toContain("wirless");
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
    mockPackagingDisclosureDependencies();
    render(<RetrievalLabPage />);

    await openPackagingDisclosure();

    // Witness, independent of any text this test reads off the page: the
    // loader actually reached the registry for both adapter surfaces, rather
    // than the assertions below passing because stray markup happened to match.
    await waitFor(() => {
      expect(api.toolContracts).toHaveBeenCalledWith("skill");
      expect(api.toolContracts).toHaveBeenCalledWith("mcp");
    });

    // Three of the four skill capabilities in the real registry are spelled
    // identically to their tool name (`db/config/agent_tool_contracts.json`), so
    // each name below renders twice: once as the tool's `<code>` and once as its
    // `<em>` capability. `findAllByText` tolerates that; the singular query would
    // throw "multiple elements" on real data.
    for (const name of [
      "search_products",
      "get_product_evidence",
      "compare_products",
      "explain_retrieval",
    ]) {
      expect((await screen.findAllByText(name)).length).toBeGreaterThan(0);
    }
  });

  it("labels A2A as documentation rather than available", async () => {
    mockPackagingDisclosureDependencies();
    render(<RetrievalLabPage />);

    await openPackagingDisclosure();

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
    mockPackagingDisclosureDependencies();
    render(<RetrievalLabPage />);

    await openPackagingDisclosure();

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
});
