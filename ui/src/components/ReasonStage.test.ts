// @vitest-environment jsdom

import { createElement } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { evidenceChain } from "./ReasonStage";
import { ReasonStage } from "./ReasonStage";
import type {
  AgentCitation,
  AgentResponse,
  EvidenceRecord,
  ProductSummary,
  ToolContract,
  ToolTraceStep,
} from "../types";

vi.mock("../api", () => ({
  api: {
    agentStream: vi.fn(),
    evidence: vi.fn(),
    toolContracts: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

/**
 * Lab 3's six states are six different things, and this is where they are held
 * apart.
 *
 * `make reset-lab-3` removes the four lines between the `LAB3_EVIDENCE_STATE`
 * markers in `service/agent_tools.get_product_evidence`. The tool still succeeds
 * and still hands the model its records — `outcome: "success"`, `result_count: 6` —
 * while the application registers nothing, so `synthesize_cited_answer` refuses
 * and the run fails closed. Every honest surface therefore has to be able to say
 * "returned to the model: yes" and "registered: no" in the same breath, and the
 * bookends carry the rest of the claim: retrieval itself succeeded (first row),
 * and the run still ended without a grounded answer (last row).
 */

function step(
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

const CHAIN_KEYS = ["retrieved", "returned", "registered", "authorized", "resolved", "answer"];

const citation: AgentCitation = {
  number: 1,
  evidence_id: 4021,
  evidence_type: "product_spec",
  product_id: 2,
  source_uri: "mosaic://catalog/2/spec",
  revision: "r3",
  title: "Battery life",
  quote: "Up to 60 hours of listening.",
};

/** The repaired run: product retrieved, evidence returned, registered, authorized,
 * resolved, and a grounded answer of record. */
const REPAIRED_TRACE: ToolTraceStep[] = [
  step(1, "search_products", { result_count: 12 }),
  step(2, "compare_products", { result_count: 2 }),
  step(3, "get_product_evidence", {
    result_count: 6,
    arguments: { product_id: 2, evidence_query: "battery" },
  }),
  step(4, "get_product_evidence", {
    result_count: 5,
    arguments: { product_id: 370002, evidence_query: "lumbar" },
  }),
  step(5, "synthesize_cited_answer", { result_count: 2 }),
];

/**
 * The measured broken run: the same successful search and the same two evidence
 * lookups succeed with the same counts, and synthesis reports why it refused.
 */
const BROKEN_TRACE: ToolTraceStep[] = [
  ...REPAIRED_TRACE.slice(0, 4),
  step(5, "synthesize_cited_answer", {
    outcome: "error",
    result_count: 0,
    detail: "Grounded synthesis blocked; missing evidence for [2, 370002].",
  }),
];

describe("evidenceChain", () => {
  it("passes all six states for a repaired, fully resolved run", () => {
    const chain = evidenceChain(REPAIRED_TRACE, [citation], true, 1);

    expect(chain.map((entry) => entry.key)).toEqual(CHAIN_KEYS);
    expect(chain.map((entry) => entry.state)).toEqual([
      "pass",
      "pass",
      "pass",
      "pass",
      "pass",
      "pass",
    ]);
    expect(chain[0].value).toBe("12 products across 1 search");
    // 6 + 5 records over two products, read off result_count.
    expect(chain[1].value).toBe("11 records over 2 products");
    expect(chain[2].value).toBe("indexed under 2 products");
    expect(chain[4].value).toBe("1 of 1 resolved");
    expect(chain[5].value).toBe("answered");
  });

  /**
   * The priority gate: retrieval succeeding while registration, authorization,
   * and the final answer all fail closed is the lab's whole point, so this
   * asserts the *relationship* between the first row and the rest -- not just
   * that each one independently holds some state.
   */
  it("keeps the first row passing while registration, authorization, and the grounded answer are blocked", () => {
    const chain = evidenceChain(BROKEN_TRACE, [], false, null);

    expect(chain.map((entry) => entry.key)).toEqual(CHAIN_KEYS);
    const [retrieved, returned, registered, authorized] = chain;
    const answer = chain[5];

    expect(retrieved.state).toBe("pass");
    expect(returned.state).toBe("pass");
    expect(returned.value).toBe("11 records over 2 products");
    expect(registered.state).toBe("blocked");
    expect(registered.value).toBe("nothing registered");
    expect(registered.source).toContain("missing evidence for [2, 370002]");
    expect(authorized.state).toBe("blocked");
    expect(authorized.value).toBe("refused");
    expect(answer.state).toBe("blocked");
    expect(answer.value).toBe("blocked");

    // The relationship this lab turns on: a passing first row next to a
    // blocked one is what proves the break sits downstream of retrieval,
    // not inside it.
    expect(retrieved.state).not.toBe(registered.state);
    expect(retrieved.state).not.toBe(authorized.state);
    expect(retrieved.state).not.toBe(answer.state);
  });

  it("reports a run that never reached synthesis as pending, not as refused registration", () => {
    // A 503 before synthesis leaves no verdict about registration either way, and
    // "nothing registered" would be a stronger claim than the trace supports.
    const chain = evidenceChain(REPAIRED_TRACE.slice(0, 4), [], false, null);

    expect(chain[0].state).toBe("pass");
    expect(chain[2].state).toBe("pending");
    expect(chain[2].value).toBe("not reached");
    expect(chain[3].state).toBe("blocked");
  });

  it("does not claim citations resolve until they have been fetched", () => {
    const chain = evidenceChain(REPAIRED_TRACE, [citation], true, null);

    expect(chain[4].state).toBe("pending");
    expect(chain[4].value).toBe("1 cited, not checked yet");
    expect(chain[4].source).toContain("open the evidence records");
  });

  it("marks resolution failed when a cited id does not come back", () => {
    const second: AgentCitation = { ...citation, number: 2, evidence_id: 9999 };
    const chain = evidenceChain(REPAIRED_TRACE, [citation, second], true, 1);

    expect(chain[4].state).toBe("blocked");
    expect(chain[4].value).toBe("1 of 2 resolved");
    expect(chain[4].source).toBe("GET /api/evidence/{evidence_id}");
  });

  it("counts distinct evidence ids, not citation numbers", () => {
    // Two claims can be supported by one record. Counting citations would report
    // two resolutions for one fetch and make a shortfall look like a success.
    const repeated: AgentCitation = { ...citation, number: 2 };
    const chain = evidenceChain(REPAIRED_TRACE, [citation, repeated], true, 1);

    expect(chain[4].value).toBe("1 of 1 resolved");
    expect(chain[4].state).toBe("pass");
  });

  it("calls nothing refused while the run is still going", () => {
    // Mid-run the trace holds a completed search and no evidence lookup yet, and
    // reading that as "returned: none / authorized: refused" told a participant
    // the run had failed while it was still working. The search itself already
    // completed, though, so that row alone reports its real, settled outcome.
    const midRun = REPAIRED_TRACE.slice(0, 2);
    const chain = evidenceChain(midRun, [], false, null, true);

    expect(chain.map((entry) => entry.state)).toEqual([
      "pass",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
    expect(chain.map((entry) => entry.value)).toEqual([
      "12 products across 1 search",
      "not yet",
      "not yet",
      "not yet",
      "0 cited, not checked yet",
      "not yet",
    ]);
    // The same trace once the run has stopped is a real refusal.
    const settled = evidenceChain(midRun, [], false, null, false);
    expect(settled.map((entry) => entry.state)).toEqual([
      "pass",
      "blocked",
      "pending",
      "blocked",
      "pending",
      "blocked",
    ]);
  });

  it("reports no evidence at all when the lookups themselves failed, even though retrieval succeeded", () => {
    const trace = [
      step(1, "search_products", { result_count: 12 }),
      step(2, "get_product_evidence", {
        outcome: "error",
        result_count: 0,
        arguments: { product_id: 2, evidence_query: "battery" },
        detail: "No evidence records were available for the retrieved product.",
      }),
    ];
    const chain = evidenceChain(trace, [], false, null);

    expect(chain[0].state).toBe("pass");
    expect(chain[1].state).toBe("blocked");
    expect(chain[1].value).toBe("none");
    expect(chain[1].source).toBe("0 successful get_product_evidence calls");
  });

  it("reports no product retrieved when search itself never succeeded", () => {
    const chain = evidenceChain([], [], false, null);

    expect(chain[0].state).toBe("blocked");
    expect(chain[0].value).toBe("none");
    expect(chain[0].source).toBe("0 successful search_products calls");
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function agentResponse(
  agentRunId: string,
  evidenceId: number,
): AgentResponse {
  return {
    agent_run_id: agentRunId,
    question: "Which product is grounded?",
    answer: `Answer from ${agentRunId}`,
    plan: [],
    recommendations: [productSummary(2, "Mosaic QuietType K8")],
    citations: [{ ...citation, evidence_id: evidenceId }],
    trace: REPAIRED_TRACE,
  };
}

function productSummary(productId: number, title: string): ProductSummary {
  return {
    product_id: productId,
    sku: `SKU-${productId}`,
    title,
    short_description: "Quiet mechanical keyboard for focused work.",
    domain: "home_office",
    category_key: "quiet-keyboards",
    category_path: "Home office > Quiet keyboards",
    brand: "Mosaic",
    model: "K8",
    price_cents: 17900,
    list_price_cents: 19900,
    currency: "USD",
    rating: 4.8,
    review_count: 82,
    availability: "in_stock",
    inventory_count: 16,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: "catalog",
    is_flagship: false,
    is_retrieval_anchor: true,
    image_url: "/assets/images/mosaic/ho-quiet-keyboards-01-catalog-3x2.webp",
    image_source: "mosaic",
    signals: null,
    sources: [],
  };
}

function evidenceRecord(evidenceId: number, title: string): EvidenceRecord {
  return {
    evidence_id: evidenceId,
    product_id: 2,
    evidence_type: "product_spec",
    source_name: "Mosaic catalog",
    source_uri: `mosaic://evidence/${evidenceId}`,
    revision: "r3",
    title,
    text: `${title} text`,
    rating: null,
    is_verified: true,
    metadata: {},
  };
}

function toolContract(name: string): ToolContract {
  return {
    name,
    capability: "retrieval",
    tool_version: "1.0",
    description: `${name} contract`,
    input_schema: {},
    output_schema: {},
    read_only: true,
  };
}

function openDisclosure(label: string) {
  const summary = screen.getByText(label).closest("summary");
  if (!summary) throw new Error(`No disclosure for ${label}`);
  fireEvent.click(summary);
}

async function runAgent() {
  fireEvent.click(screen.getByRole("button", { name: /Run (the agent|agent again)/ }));
  await screen.findByRole("button", { name: "Run agent again" });
}

describe("ReasonStage composer", () => {
  it("renders the canonical question as an editable multiline prompt", () => {
    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: {},
    }));

    const prompt = screen.getByRole("textbox", { name: "Question for Mosaic" });
    expect(prompt.tagName).toBe("TEXTAREA");
    expect((prompt as HTMLTextAreaElement).value).toBe("Which product is grounded?");
    expect(screen.getByText("Enter to run. Shift+Enter for a new line.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run the agent" })).toBeTruthy();
  });

  it("submits an edited question with Enter and keeps Shift+Enter for a newline", async () => {
    vi.mocked(api.agentStream).mockResolvedValue(undefined);
    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: { in_stock_only: true },
    }));

    const prompt = screen.getByRole("textbox", { name: "Question for Mosaic" });
    fireEvent.change(prompt, {
      target: { value: "Compare the quietest keyboard and chair." },
    });
    fireEvent.keyDown(prompt, { key: "Enter", code: "Enter", shiftKey: true });
    expect(api.agentStream).not.toHaveBeenCalled();

    fireEvent.keyDown(prompt, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      expect(api.agentStream).toHaveBeenCalledWith(
        "Compare the quietest keyboard and chair.",
        { in_stock_only: true },
        expect.any(Function),
      );
    });
  });
});

describe("ReasonStage evidence resolution", () => {
  it("shows the retrieved product and frames synthesis as citation eligibility", async () => {
    const response = agentResponse("run-visual", 4021);
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({ type: "complete", response });
    });

    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: {},
    }));
    await runAgent();

    const image = screen.getByRole("img", { name: "Mosaic QuietType K8" });
    expect(image.getAttribute("src")).toContain("/assets/images/mosaic/");
    expect(screen.getByText("Answer evidence boundary")).toBeTruthy();
    expect(screen.getByText("Evidence authorized for synthesis")).toBeTruthy();
    expect(screen.queryByText(/authentication or RBAC/i)).toBeNull();
  });

  it("ignores evidence from an older run when requests resolve in reverse order", async () => {
    const oldEvidence = deferred<EvidenceRecord>();
    const currentEvidence = deferred<EvidenceRecord>();
    const responses = [
      agentResponse("run-old", 4021),
      agentResponse("run-current", 9002),
    ];
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      const response = responses.shift();
      if (!response) throw new Error("No response fixture");
      onEvent({ type: "complete", response });
    });
    vi.mocked(api.evidence).mockImplementation((id) => (
      id === 9002 ? currentEvidence.promise : oldEvidence.promise
    ));

    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: {},
    }));

    await runAgent();
    await waitFor(() => {
      expect(vi.mocked(api.evidence)).toHaveBeenCalledWith(4021);
    });

    await runAgent();
    await waitFor(() => {
      expect(vi.mocked(api.evidence)).toHaveBeenCalledWith(9002);
    });

    await act(async () => {
      currentEvidence.resolve(evidenceRecord(9002, "Current run evidence"));
    });
    expect(await screen.findByText("Current run evidence")).toBeTruthy();

    await act(async () => {
      oldEvidence.resolve(evidenceRecord(4021, "Old run evidence"));
    });
    await waitFor(() => {
      expect(screen.getByText("Current run evidence")).toBeTruthy();
      expect(screen.queryByText("Old run evidence")).toBeNull();
    });
  });

  it("retries evidence resolution after a transient failure", async () => {
    const response = agentResponse("run-retry", 4021);
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({ type: "complete", response });
    });
    vi.mocked(api.evidence)
      .mockRejectedValueOnce(new Error("temporary evidence failure"))
      .mockResolvedValueOnce(evidenceRecord(4021, "Recovered evidence"));

    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: {},
    }));
    await runAgent();
    await screen.findByRole("alert");
    openDisclosure("View evidence records");

    expect(screen.getByRole("alert").textContent).toContain(
      "1 of 1 cited evidence ids did not resolve",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry evidence records" }));

    expect(await screen.findByText("Recovered evidence")).toBeTruthy();
    expect(screen.queryByText(/did not resolve/)).toBeNull();
    expect(vi.mocked(api.evidence)).toHaveBeenCalledTimes(2);
  });

  it("retries the tool contract after a transient failure", async () => {
    const response = agentResponse("run-contract", 4021);
    vi.mocked(api.agentStream).mockImplementation(async (_question, _filters, onEvent) => {
      onEvent({ type: "complete", response });
    });
    vi.mocked(api.evidence).mockResolvedValue(
      evidenceRecord(4021, "Contract test evidence"),
    );
    vi.mocked(api.toolContracts)
      .mockRejectedValueOnce(new Error("temporary contract failure"))
      .mockResolvedValueOnce([toolContract("search_products")]);

    render(createElement(ReasonStage, {
      question: "Which product is grounded?",
      filters: {},
    }));
    await runAgent();
    openDisclosure("View tool contract");

    expect((await screen.findByRole("alert")).textContent).toContain(
      "temporary contract failure",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry tool contract" }));

    expect(await screen.findByText("search_products")).toBeTruthy();
    expect(screen.queryByText("temporary contract failure")).toBeNull();
    expect(vi.mocked(api.toolContracts)).toHaveBeenCalledTimes(2);
  });
});
