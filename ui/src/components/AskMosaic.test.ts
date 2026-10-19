// @vitest-environment jsdom

import { createElement } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommerceProvider } from "../commerce";
import { fixtureCatalogPage } from "../testProducts";
import { AskMosaic } from "./AskMosaic";
import { boldRecommendationNames } from "./ask-mosaic/emphasis";
import type { AskMosaicTurn } from "./ask-mosaic/types";
import { Searches } from "./agentAnswerParts";
import { pipelineRequests } from "../labMissions";
import type { AgentPlanStep, AgentResponse, ToolTraceStep } from "../types";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

const [first, second] = fixtureCatalogPage({}, 0, 2).products;

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
    startedAt: Date.now(),
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
    expect(screen.queryByText("The Retrieval agent could not confirm part of this request")).toBeNull();
    expect(screen.queryByText(/drop the term named above/)).toBeNull();
  });

  it("renders the declined block with the run's fold, and no picks or sources", () => {
    renderAskMosaic(DECLINED_RESPONSE);

    expect(
      screen.getByText("The Retrieval agent could not confirm part of this request"),
    ).toBeTruthy();
    expect(screen.getByText(DECLINED_RESPONSE.answer)).toBeTruthy();
    expect(
      screen.getByText(
        "Check the product name or spelling, or inspect the sources before trying again.",
      ),
    ).toBeTruthy();

    // What was actually tried stays one click away, with nothing to recommend.
    const fold = screen.getByRole("button", { name: /How the tools work/ });
    expect(fold.textContent).toContain("1 search");
    expect(fold.textContent).toContain("0 sources");
    fireEvent.click(fold);
    expect(screen.getByText(/Ran 1 search in Aurora and kept 3 products/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Sources" })).toBeNull();
    expect(screen.queryByLabelText(/Top pick/)).toBeNull();
  });

  it("leaves a grounded fixture unchanged", () => {
    renderAskMosaic(groundedResponse());

    expect(
      screen.queryByText("The Retrieval agent could not confirm part of this request"),
    ).toBeNull();
    expect(screen.getByText("Final recommendation")).toBeTruthy();
    expect(screen.getByLabelText(`Top pick: ${first.brand} ${first.model}`.trim())).toBeTruthy();
    expect(screen.getByRole("region", { name: "Sources" })).toBeTruthy();
    expect(screen.queryByText("Still unknown")).toBeNull();
  });

  it("does not describe a failed application-started step as completed", () => {
    window.localStorage.setItem("mosaic-ask-builder-view", "on");
    const response = groundedResponse();
    response.trace = [traceStep(1, "get_product_evidence", { origin: "controller_fallback", outcome: "error" })];
    renderAskMosaic(response);
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
      screen.getByText("The partial answer and steps above are what the Retrieval agent had found so far."),
    ).toBeTruthy();
    // `role="alert"` is reserved for `turn.error`; cancellation is not a
    // failure and must never be announced as one.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("The Retrieval agent could not finish this request.")).toBeNull();
  });
});

describe("AskMosaic failures", () => {
  const setupDetail = "Your Retrieval agent is not built yet. Open labs/lab3_reason/agent.py in Code Editor "
    + "and complete create_agent with the supplied model, tools, instructions and hooks. "
    + "Next: deploy with uv run python scripts/deploy_agentcore.py deploy, then ask your "
    + "question again.";

  function failedTurn(error: string, errorCode?: string): AskMosaicTurn {
    return {
      ...settledTurn(groundedResponse()),
      response: null,
      completed: false,
      error,
      errorCode,
    };
  }

  it("shows an unbuilt agent as a next step with a copyable command", () => {
    renderAskMosaic(groundedResponse(), { turns: [failedTurn(setupDetail, "agent_setup")] });

    const card = screen.getByRole("status", { name: "Finish setting up your Retrieval agent" });
    expect(within(card).getByText(/Your Retrieval agent is not built yet/)).toBeTruthy();
    expect(card.querySelector("code")?.textContent)
      .toBe("uv run python scripts/deploy_agentcore.py deploy");
    expect(
      within(card).getByRole("button", {
        name: "Copy uv run python scripts/deploy_agentcore.py deploy",
      }),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/share this message with your facilitator/)).toBeNull();
  });

  it("shows a Gateway outage with an agent_setup code as an error with its full text", () => {
    const outage = "Gateway could not complete the tool request. Next: check the deployment with "
      + "uv run python scripts/deploy_agentcore.py verify in Code Editor; ask your facilitator to "
      + "inspect the Gateway target if it fails.";
    renderAskMosaic(groundedResponse(), { turns: [failedTurn(outage, "agent_setup")] });

    expect(screen.getByRole("alert").textContent).toContain(outage);
    expect(screen.queryByRole("status", { name: "Finish setting up your Retrieval agent" })).toBeNull();
  });

  it("keeps the retry advice for a transient failure", () => {
    renderAskMosaic(groundedResponse(), {
      turns: [failedTurn("Model service unavailable.", "agent_turn_deadline")],
    });

    expect(screen.getByRole("alert").textContent).toMatch(/Press Ask again to retry/);
  });
});

describe("AskMosaic starters", () => {
  it("shows a lesson line and the request as a clue, and describes the card with the lesson", () => {
    const starters = pipelineRequests.filter((request) => request.id === "plan-workspace" || request.id === "more-screen-space");
    renderAskMosaic(groundedResponse(), { turns: [], suggestions: starters });

    const list = screen.getByRole("list", { name: "Example questions" });
    for (const starter of starters) {
      const button = within(list).getByRole("button", { name: starter.shop_label });
      const lesson = button.querySelector(".ask-start-lesson")!;
      expect(lesson.textContent).toMatch(/^Lab [23]: /);
      expect(button.getAttribute("aria-describedby")).toBe(lesson.id);
      expect(button.querySelector(".ask-start-clue")?.textContent).toBe(starter.query);
      expect(within(button).queryByText(starter.notice)).toBeNull();
    }
  });

  it("keeps the title and clue when a starter has no lesson line", () => {
    const [starter] = pipelineRequests;
    renderAskMosaic(groundedResponse(), { turns: [], suggestions: [{ ...starter, id: "unlisted" }] });

    const button = within(screen.getByRole("list", { name: "Example questions" })).getByRole("button");
    expect(button.querySelector(".ask-start-lesson")).toBeNull();
    expect(button.hasAttribute("aria-describedby")).toBe(false);
    expect(button.textContent).toContain(starter.shop_label);
  });
});

describe("AskMosaic header and Builder view", () => {
  it("starts with Builder view off and no recorded steps on the page", () => {
    renderAskMosaic(groundedResponse());

    const toggle = screen.getByRole("switch", { name: "Show tool calls" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByRole("region", { name: "Builder view" })).toBeNull();
    expect(screen.getByRole("button", { name: /How the tools work/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("turns the recorded steps on page-wide and remembers the choice", () => {
    renderAskMosaic(groundedResponse());

    fireEvent.click(screen.getByRole("switch", { name: "Show tool calls" }));

    expect(screen.getByRole("switch", { name: "Show tool calls" }).getAttribute("aria-checked")).toBe("true");
    const builder = screen.getByRole("region", { name: "Builder view" });
    expect(within(builder).getByText("run-grounded")).toBeTruthy();
    for (const field of ["model id", "tokens", "Gateway target", "claim verdicts"]) {
      expect(within(builder).queryByText(field)).toBeNull();
    }
    expect(window.localStorage.getItem("mosaic-ask-builder-view")).toBe("on");
    cleanup();
    renderAskMosaic(groundedResponse());
    expect(screen.getByRole("switch", { name: "Show tool calls" }).getAttribute("aria-checked")).toBe("true");
  });

  it("still switches for the visit when the browser refuses storage", () => {
    const refuse = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    renderAskMosaic(groundedResponse());

    fireEvent.click(screen.getByRole("switch", { name: "Show tool calls" }));

    expect(screen.getByRole("switch", { name: "Show tool calls" }).getAttribute("aria-checked")).toBe("true");
    refuse.mockRestore();
  });

  it("offers clear chat and close as icon buttons with names", () => {
    let cleared = false;
    renderAskMosaic(groundedResponse(), { onClear: () => { cleared = true; } });

    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(cleared).toBe(true);
    expect(screen.getAllByRole("button", { name: "Close Ask Mosaic" }).length).toBeGreaterThan(0);
  });

  it("leaves the time out of the fold when the turn carries no measured timing", () => {
    renderAskMosaic(groundedResponse());

    const fold = screen.getByRole("button", { name: /How the tools work/ });
    expect(fold.textContent).toContain("1 search");
    expect(fold.textContent).not.toMatch(/\d s\b/);
  });

  it("names the pick a top pick, never the best", () => {
    renderAskMosaic(groundedResponse());

    const card = screen.getByLabelText(/Top pick/);
    expect(within(card).getByText("Top pick")).toBeTruthy();
    expect(screen.queryByText(/Best fit/)).toBeNull();
  });

  it("turns a citation number in the answer into a chip that names its source", () => {
    renderAskMosaic(groundedResponse());

    const prose = document.querySelector(".ask-prose") as HTMLElement;
    expect(within(prose).getByRole("link", { name: "Source 1" }).textContent).toBe("1");
    expect(prose.textContent).not.toContain("[1]");
  });
});

function scrollableThread() {
  const thread = document.querySelector<HTMLElement>(".ask-mosaic-body")!;
  Object.defineProperties(thread, {
    clientHeight: { configurable: true, value: 300 },
    scrollHeight: { configurable: true, value: 1200 },
    scrollTop: { configurable: true, writable: true, value: 900 },
  });
  return thread;
}

describe("AskMosaic jump to latest", () => {
  const JUMP = { name: "Jump to latest" };

  it("stays hidden for a reader who scrolled up while nothing new arrived", () => {
    renderAskMosaic(groundedResponse());
    const thread = scrollableThread();
    thread.scrollTop = 100;
    fireEvent.scroll(thread);

    expect(screen.queryByRole("button", JUMP)).toBeNull();
  });

  it("appears, docked above the composer, once new content lands below a reader who scrolled up", async () => {
    const response = groundedResponse();
    const writing: AskMosaicTurn = {
      ...settledTurn(response),
      completed: false,
      loading: true,
      stage: "answer",
      executionPath: "focused_follow_up",
      streamed: `${response.answer} `.repeat(6),
    };
    renderAskMosaic(response, { turns: [writing], pending: true });
    const thread = scrollableThread();
    thread.scrollTop = 100;
    fireEvent.scroll(thread);

    const jump = await screen.findByRole("button", JUMP, { timeout: 6000 });
    expect(jump.closest(".ask-mosaic-composer")).not.toBeNull();
    expect(thread.contains(jump)).toBe(false);

    act(() => { fireEvent.click(jump); });
    expect(thread.scrollTop).toBe(1200);
    await waitFor(() => expect(screen.queryByRole("button", JUMP)).toBeNull());
  }, 12000);
});

describe("AskMosaic declined reads as declined", () => {
  it("announces a declined turn as declined, with a neutral icon", () => {
    const { container } = renderAskMosaic(DECLINED_RESPONSE);

    const statuses = screen.getAllByRole("status").map((status) => status.textContent);
    expect(statuses).toContain("The Retrieval agent declined to recommend a product.");
    expect(statuses.join(" ")).not.toMatch(/recommendation/);
    const fold = container.querySelector(".ask-fold");
    expect(fold?.hasAttribute("data-declined")).toBe(true);
    expect(fold?.querySelector("svg.lucide-check")).toBeNull();
  });

  it("keeps the check for a grounded answer", () => {
    const { container } = renderAskMosaic(groundedResponse());

    expect(screen.getAllByRole("status").map((status) => status.textContent))
      .toContain("The Retrieval agent finished its recommendation.");
    expect(container.querySelector(".ask-fold svg.lucide-check")).not.toBeNull();
  });
});

describe("AskMosaic citation chips", () => {
  const chips = (container: HTMLElement) => [...container.querySelectorAll<HTMLAnchorElement>("a.ask-answer-cite")];

  it("makes chips inert while the sources are not on screen, then live", () => {
    const response = groundedResponse();
    const stopped: AskMosaicTurn = {
      ...settledTurn(response),
      completed: false,
      cancelled: true,
      streamed: response.answer,
    };
    const { container } = renderAskMosaic(response, { turns: [stopped] });

    expect(screen.queryByRole("region", { name: "Sources" })).toBeNull();
    const [chip] = chips(container);
    expect(chip.getAttribute("aria-disabled")).toBe("true");
    expect(chip.tabIndex).toBe(-1);
    expect(fireEvent.click(chip)).toBe(false);
    expect(container.querySelector(".ask-mosaic-answer")?.getAttribute("data-sources")).toBe("pending");

    cleanup();
    const settled = renderAskMosaic(response);
    const [live] = chips(settled.container);
    expect(live.hasAttribute("aria-disabled")).toBe(false);
    expect(settled.container.querySelector(".ask-mosaic-answer")?.getAttribute("data-sources")).toBe("ready");
  });
});

describe("AskMosaic tool chips above the answer", () => {
  it("keeps one chip per recorded call over the finished answer", () => {
    renderAskMosaic(groundedResponse());

    const list = screen.getByRole("list", { name: "Tools the Retrieval agent called" });
    expect(within(list).getByText("Search").closest("li")?.getAttribute("data-state")).toBe("done");
    expect(within(list).getByText("12 ms")).toBeTruthy();
    expect(screen.queryByLabelText("Progress")).toBeNull();
  });

  it("shows a failed call in red and a declined call in grey, without a time that was not recorded", () => {
    const response = groundedResponse();
    response.trace = [
      traceStep(1, "get_product_evidence", { outcome: "error", latency_ms: null }),
      traceStep(2, "synthesize_cited_answer", { outcome: "denied", latency_ms: null }),
    ];
    renderAskMosaic(response);

    const list = screen.getByRole("list", { name: "Tools the Retrieval agent called" });
    const read = within(list).getByText("Read sources").closest("li")!;
    const write = within(list).getByText("Write cited answer").closest("li")!;
    expect(read.getAttribute("data-state")).toBe("failed");
    expect(write.getAttribute("data-state")).toBe("denied");
    expect(list.textContent).not.toMatch(/ms/);
  });
});

describe("AskMosaic conversation", () => {
  const second = (response: AgentResponse): AskMosaicTurn => ({
    ...settledTurn(response),
    id: 2,
    question: "And a cheaper one?",
  });

  it("collapses earlier turns under Previous messages and offers a visible New conversation", () => {
    const response = groundedResponse();
    const onClear = vi.fn();
    renderAskMosaic(response, { turns: [settledTurn(response), second(response)], onClear });

    expect(screen.getAllByText("You asked")).toHaveLength(1);
    const toggle = screen.getByRole("button", { name: /Previous messages/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getAllByText("You asked")).toHaveLength(2);

    const fresh = screen.getByRole("button", { name: "New conversation" });
    expect(fresh.textContent).toBe("New conversation");
    fireEvent.click(fresh);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("has no Previous messages on the first turn", () => {
    renderAskMosaic(groundedResponse());
    expect(screen.queryByRole("button", { name: /Previous messages/ })).toBeNull();
  });

  it("lets Stop take the Send button's place while a run is going", () => {
    const onStop = vi.fn();
    renderAskMosaic(groundedResponse(), { pending: true, onStop });

    expect(screen.queryByRole("button", { name: "Send request" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Working on your request")).toBeNull();
  });

  it("says the price and stock caveat once, not under the picks", () => {
    renderAskMosaic(groundedResponse());
    expect(screen.getAllByText(/not the current listing/)).toHaveLength(1);
  });
});

describe("AskMosaic found-by dots", () => {
  it("names the searches that found a pick from its own signals", () => {
    const response = groundedResponse();
    const rank = (value: number | null) => ({ rank: value, raw_score: null, rrf_contribution: null });
    response.recommendations = [{
      ...first,
      signals: {
        fts: rank(1), trigram: rank(null), semantic: rank(4),
        rrf_score: 0.03, pre_rerank_rank: 2, pre_rerank_score: 0.03, rerank_score: null,
        final_rank: 1, score_semantics: "",
      },
    }];
    renderAskMosaic(response);

    const found = screen.getByRole("group", { name: "Found by" });
    expect([...found.querySelectorAll("span")].map((item) => item.textContent))
      .toEqual(["Full-text search", "Semantic search"]);
  });
});
