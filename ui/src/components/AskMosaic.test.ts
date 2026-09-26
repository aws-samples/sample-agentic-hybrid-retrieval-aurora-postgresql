// @vitest-environment jsdom

import { createElement } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage } from "../showcase";
import { AskMosaic, boldRecommendationNames } from "./AskMosaic";
import type { AskMosaicTurn } from "./ask-mosaic/types";
import { Searches } from "./agentAnswerParts";
import type { AgentPlanStep, AgentResponse, ToolTraceStep } from "../types";

afterEach(() => {
  cleanup();
});

const [first, second] = showcaseCatalogPage({}, 0, 2).products;

describe("boldRecommendationNames", () => {
  it("bolds grounded product titles and brand-model references", () => {
    const answer = [
      `${first.title} is the best fit [1].`,
      `${second.brand} ${second.model} is another strong option [2].`,
    ].join("\n\n");

    expect(boldRecommendationNames(answer, [first, second])).toBe(
      [
        `**${first.title}** is the best fit [1].`,
        `**${second.brand} ${second.model}** is another strong option [2].`,
      ].join("\n\n"),
    );
  });

  it("does not double-wrap emphasis already authored by synthesis", () => {
    const answer = `**${first.title}** is the best fit [1].`;

    expect(boldRecommendationNames(answer, [first])).toBe(answer);
  });

  it("leaves product-like prose alone when it is not in the shortlist", () => {
    const answer = "A different product would be cheaper.";

    expect(boldRecommendationNames(answer, [first])).toBe(answer);
  });
});

describe("Searches", () => {
  /**
   * Ask Mosaic's call site passes no props, so the shared component's own
   * default must keep Shop's receipt collapsed behind a click. The Reason
   * stage opts into `open` explicitly (see ReasonStage.test.tsx); this is the
   * other half of that contrast.
   */
  it("keeps the searches receipt collapsed by default, the way Shop calls it", () => {
    const plan: AgentPlanStep[] = [
      { query: "quiet mechanical keyboard", filters: {}, purpose: "Find the quietest keyboards" },
    ];
    render(createElement(Searches, { plan }));

    const details = screen.getByText("Searches behind this answer").closest("details");
    expect(details?.hasAttribute("open")).toBe(false);
  });
});

function traceStep(
  sequence: number,
  tool: string,
  overrides: Partial<ToolTraceStep> = {},
): ToolTraceStep {
  return {
    sequence,
    tool,
    detail: "",
    retrieval_run_id: null,
    result_count: null,
    arguments: {},
    outcome: "success",
    latency_ms: 12,
    ...overrides,
  };
}

const DECLINED_RESPONSE: AgentResponse = {
  agent_run_id: "run-declined",
  question: "Do you sell jetpacks?",
  answer: "The catalog does not carry jetpacks, so there is nothing to recommend for that term.",
  plan: [
    { query: "jetpack propulsion pack", filters: {}, purpose: "Search for jetpack propulsion pack" },
  ],
  recommendations: [],
  citations: [],
  trace: [traceStep(1, "search_products", { result_count: 3 })],
  outcome: "declined",
  decline_reason: "jetpacks",
};

function groundedResponse(): AgentResponse {
  return {
    agent_run_id: "run-grounded",
    question: "Quiet keyboard please",
    answer: `${first.title} is a great fit [1].`,
    plan: [
      { query: "quiet mechanical keyboard", filters: {}, purpose: "Search for quiet keyboards" },
    ],
    recommendations: [first],
    citations: [
      {
        number: 1,
        evidence_id: 4021,
        evidence_type: "product_spec",
        product_id: first.product_id,
        source_uri: "mosaic://catalog/spec",
        revision: "r1",
        title: "Spec",
        quote: "Quiet switches.",
      },
    ],
    trace: [traceStep(1, "search_products", { result_count: 6 })],
  };
}

/**
 * A turn that is already settled at mount, the way `ReasonStage.test.tsx`
 * builds its fixtures: `loading: false` from the start makes `Turn`'s
 * progressive reveal instant, so the panel renders synchronously instead of
 * pacing a typewriter animation across real frames.
 */
function settledTurn(response: AgentResponse): AskMosaicTurn {
  return {
    id: 1,
    question: response.question,
    response,
    completed: true,
    partial: null,
    streamed: "",
    stage: "answer",
    stageStartedAt: Date.now(),
    executionPath: "full_retrieval",
    stageDetail: "",
    error: "",
    cancelled: false,
    loading: false,
  };
}

function renderAskMosaic(
  response: AgentResponse,
  overrides: Partial<Parameters<typeof AskMosaic>[0]> = {},
) {
  return render(
    createElement(
      CommerceProvider,
      null,
      createElement(AskMosaic, {
        open: true,
        seedQuery: "",
        contextFilters: [],
        turns: [settledTurn(response)],
        pending: false,
        suggestions: [],
        imageByProductId: new Map(),
        highlightedProductId: null,
        onClose: () => {},
        onClear: () => {},
        onStop: () => {},
        onRun: () => {},
        onHighlight: () => {},
        onSelectProduct: () => {},
        ...overrides,
      }),
    ),
  );
}

describe("AskMosaic declined outcome", () => {
  it("shows empty filtered searches without calling them a runtime or catalog fault", () => {
    renderAskMosaic({
      ...DECLINED_RESPONSE,
      answer: "No products matched this request with the current search filters.",
      decline_reason: "no_matching_products",
      trace: [traceStep(1, "search_products", { result_count: 0 })],
    });
    expect(screen.getByText("No products matched this search")).toBeTruthy();
    expect(screen.getByText(/Your filters stayed in place/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/This is a catalog gap/)).toBeNull();
  });

  it("distinguishes missing review evidence from a missing catalog product", () => {
    renderAskMosaic({
      ...DECLINED_RESPONSE,
      question: "What do the specs and reviews say about OH-M349?",
      plan: [],
      decline_reason: "insufficient_evidence",
      answer: "The available sources do not provide enough detail to answer this request.",
    });
    expect(screen.getByText("The sources do not answer this yet")).toBeTruthy();
    expect(screen.queryByText("Mosaic could not confirm part of this request")).toBeNull();
    expect(screen.queryByText(/drop the term named above/)).toBeNull();
  });

  it("renders the declined block, hides the shortlist and compare/cite panels, and keeps the searches list", () => {
    renderAskMosaic(DECLINED_RESPONSE);

    expect(
      screen.getByText("Mosaic could not confirm part of this request"),
    ).toBeTruthy();
    expect(screen.getByText(DECLINED_RESPONSE.answer)).toBeTruthy();
    expect(
      screen.getByText(
        "Check the product name or spelling, or inspect the sources before trying again.",
      ),
    ).toBeTruthy();

    // The answer leads; the actual searches remain available to inspect.
    const process = screen.getByText("Steps and sources").closest("details")!;
    expect(process.open).toBe(false);
    fireEvent.click(screen.getByText("Steps and sources"));
    expect(process.open).toBe(true);
    // No compare panel exists to open:
    // recommendations are empty by contract on a declined answer, so the
    // comparison stage never has a panel to disclose.
    expect(screen.getByLabelText("Retrieval activity")).toBeTruthy();
    expect(screen.queryByText("Side by side, on catalog data")).toBeNull();

    // The "Retrieval" step still discloses the searches that were
    // tried, with no shortlist beside them.
    openStage("Retrieval");
    expect(screen.queryByText("The shortlist")).toBeNull();
    const searchesDetails = screen.getByText("Searches behind this answer").closest("details");
    expect(searchesDetails).not.toBeNull();
    fireEvent.click(screen.getByText("Searches behind this answer"));
    expect(
      within(searchesDetails as HTMLElement).getByText("jetpack propulsion pack"),
    ).toBeTruthy();

    // The "Sources" step still discloses what the agent did; there are no
    // citations to disclose beside it.
    openStage("Sources");
    expect(screen.queryByText("Evidence it cited")).toBeNull();
    expect(screen.getByText("Recorded steps")).toBeTruthy();
    expect(screen.queryByText("No evidence cited")).toBeNull();
  });

  it("leaves a grounded fixture unchanged", () => {
    renderAskMosaic(groundedResponse());

    expect(
      screen.queryByText("Mosaic could not confirm part of this request"),
    ).toBeNull();
    expect(screen.getByText("Final recommendation")).toBeTruthy();
    expect(screen.getByText("Backed by evidence")).toBeTruthy();

    openStage("Retrieval");
    expect(screen.getByText("The shortlist")).toBeTruthy();
  });

  it("does not describe a failed application-started step as completed", () => {
    const response = groundedResponse();
    response.trace = [traceStep(1, "get_product_evidence", { origin: "controller_fallback", outcome: "error" })];
    renderAskMosaic(response);
    openStage("Sources");
    fireEvent.click(screen.getByText("Recorded steps"));
    expect(screen.getByText("Started by the application")).toBeTruthy();
    expect(screen.getByText("Step failed")).toBeTruthy();
    expect(screen.queryByText("Step completed")).toBeNull();
  });
});

describe("AskMosaic cancellation", () => {
  it("shows a Stop control while a request is pending and calls onStop when pressed", () => {
    let stopped = false;
    const onStop = () => { stopped = true; };
    renderAskMosaic(groundedResponse(), { pending: true, onStop });

    const stopButton = screen.getByRole("button", { name: "Stop generating" });
    fireEvent.click(stopButton);
    expect(stopped).toBe(true);
  });

  it("does not show a Stop control once nothing is pending", () => {
    renderAskMosaic(groundedResponse(), { pending: false });
    expect(screen.queryByRole("button", { name: "Stop generating" })).toBeNull();
  });

  it("renders a stopped turn as a normal status, never as an alert", () => {
    const response = groundedResponse();
    const turn: AskMosaicTurn = {
      ...settledTurn(response),
      completed: false,
      loading: false,
      cancelled: true,
      streamed: "The Sonora headphones are quiet enough for",
      stage: null,
    };
    renderAskMosaic(response, { turns: [turn] });

    expect(screen.getByText("You stopped this request.")).toBeTruthy();
    expect(
      screen.getByText("The partial answer and steps above are what Mosaic had found so far."),
    ).toBeTruthy();
    // `role="alert"` is reserved for `turn.error`; cancellation is not a
    // failure and must never be announced as one.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Mosaic could not finish this request.")).toBeNull();
  });
});

/** Opens a step's disclosure panel by clicking its summary in the steps rail. */
function openStage(label: string) {
  const button = screen.getByText(label).closest("button");
  if (!button) throw new Error(`No stage button for ${label}`);
  fireEvent.click(button);
}
