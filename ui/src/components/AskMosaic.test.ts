// @vitest-environment jsdom

import { createElement } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage } from "../showcase";
import { AskMosaic, boldRecommendationNames, type AskMosaicTurn } from "./AskMosaic";
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

    const details = screen.getByText("How I searched").closest("details");
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
    loading: false,
  };
}

function renderAskMosaic(response: AgentResponse) {
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
        examples: [],
        imageByProductId: new Map(),
        highlightedProductId: null,
        onClose: () => {},
        onClear: () => {},
        onRun: () => {},
        onHighlight: () => {},
        onSelectProduct: () => {},
      }),
    ),
  );
}

describe("AskMosaic declined outcome", () => {
  it("renders the declined block, hides the shortlist and compare/cite panels, and keeps the searches list", () => {
    renderAskMosaic(DECLINED_RESPONSE);

    expect(
      screen.getByText("Nothing in the catalog matches part of this request"),
    ).toBeTruthy();
    expect(screen.getByText(DECLINED_RESPONSE.answer)).toBeTruthy();
    expect(
      screen.getByText(
        "This is a catalog gap, not a retrieval fault. Try different words or"
        + " drop the term named above.",
      ),
    ).toBeTruthy();

    // The steps timeline stays visible, and no compare panel exists to open:
    // recommendations are empty by contract on a declined answer, so the
    // comparison stage never has a panel to disclose.
    expect(screen.getByLabelText("Steps I took")).toBeTruthy();
    expect(screen.queryByText("Side by side, on catalog data")).toBeNull();

    // The "Recommendations" step still discloses the searches that were
    // tried, with no shortlist beside them.
    openStage("Recommendations");
    expect(screen.queryByText("The shortlist")).toBeNull();
    const searchesDetails = screen.getByText("How I searched").closest("details");
    expect(searchesDetails).not.toBeNull();
    fireEvent.click(screen.getByText("How I searched"));
    expect(
      within(searchesDetails as HTMLElement).getByText("jetpack propulsion pack"),
    ).toBeTruthy();

    // The "Why these" step still discloses what the agent did; there are no
    // citations to disclose beside it.
    openStage("Why these");
    expect(screen.queryByText("Evidence it cited")).toBeNull();
    expect(screen.getByText("What the agent did")).toBeTruthy();
    expect(screen.queryByText("No evidence cited")).toBeNull();
  });

  it("leaves a grounded fixture unchanged", () => {
    renderAskMosaic(groundedResponse());

    expect(
      screen.queryByText("Nothing in the catalog matches part of this request"),
    ).toBeNull();
    expect(screen.getByText("Final recommendation")).toBeTruthy();
    expect(screen.getByText("Backed by evidence")).toBeTruthy();

    openStage("Recommendations");
    expect(screen.getByText("The shortlist")).toBeTruthy();
  });
});

/** Opens a step's disclosure panel by clicking its summary in the steps rail. */
function openStage(label: string) {
  const button = screen.getByText(label).closest("button");
  if (!button) throw new Error(`No stage button for ${label}`);
  fireEvent.click(button);
}
