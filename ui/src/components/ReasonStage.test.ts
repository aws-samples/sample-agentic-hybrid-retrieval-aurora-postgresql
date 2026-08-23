import { describe, expect, it } from "vitest";
import { evidenceChain } from "./ReasonStage";
import type { AgentCitation, ToolTraceStep } from "../types";

/**
 * Lab 3's four states are four different things, and this is where they are held
 * apart.
 *
 * `make reset-lab-3` removes the four lines between the `LAB3_EVIDENCE_STATE`
 * markers in `service/agent_tools.get_product_evidence`. The tool still succeeds
 * and still hands the model its records — `outcome: "success"`, `result_count: 6` —
 * while the application registers nothing, so `synthesize_cited_answer` refuses
 * and the run fails closed. Every honest surface therefore has to be able to say
 * "returned to the model: yes" and "registered: no" in the same breath.
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

/** The repaired run: evidence returned, registered, authorized, and resolved. */
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
 * The measured broken run: the same two evidence lookups succeed with the same
 * counts, and synthesis reports why it refused.
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
  it("passes all four states for a repaired, fully resolved run", () => {
    const chain = evidenceChain(REPAIRED_TRACE, [citation], true, 1);

    expect(chain.map((entry) => entry.key)).toEqual([
      "returned",
      "registered",
      "authorized",
      "resolved",
    ]);
    expect(chain.map((entry) => entry.state)).toEqual([
      "pass",
      "pass",
      "pass",
      "pass",
    ]);
    // 6 + 5 records over two products, read off result_count.
    expect(chain[0].value).toBe("11 records over 2 products");
    expect(chain[1].value).toBe("indexed under 2 products");
    expect(chain[3].value).toBe("1 of 1 resolved");
  });

  it("keeps returned-to-the-model true while registration is blocked", () => {
    // The distinction the whole lab turns on. The tool succeeded; the application
    // did not keep what it returned.
    const chain = evidenceChain(BROKEN_TRACE, [], false, null);
    const [returned, registered, authorized] = chain;

    expect(returned.state).toBe("pass");
    expect(returned.value).toBe("11 records over 2 products");
    expect(registered.state).toBe("blocked");
    expect(registered.value).toBe("nothing registered");
    expect(registered.source).toContain("missing evidence for [2, 370002]");
    expect(authorized.state).toBe("blocked");
    expect(authorized.value).toBe("refused");
  });

  it("reports a run that never reached synthesis as pending, not as refused registration", () => {
    // A 503 before synthesis leaves no verdict about registration either way, and
    // "nothing registered" would be a stronger claim than the trace supports.
    const chain = evidenceChain(REPAIRED_TRACE.slice(0, 4), [], false, null);

    expect(chain[1].state).toBe("pending");
    expect(chain[1].value).toBe("not reached");
    expect(chain[2].state).toBe("blocked");
  });

  it("does not claim citations resolve until they have been fetched", () => {
    const chain = evidenceChain(REPAIRED_TRACE, [citation], true, null);

    expect(chain[3].state).toBe("pending");
    expect(chain[3].value).toBe("1 cited, not checked yet");
    expect(chain[3].source).toContain("open the evidence records");
  });

  it("marks resolution failed when a cited id does not come back", () => {
    const second: AgentCitation = { ...citation, number: 2, evidence_id: 9999 };
    const chain = evidenceChain(REPAIRED_TRACE, [citation, second], true, 1);

    expect(chain[3].state).toBe("blocked");
    expect(chain[3].value).toBe("1 of 2 resolved");
    expect(chain[3].source).toBe("GET /api/evidence/{evidence_id}");
  });

  it("counts distinct evidence ids, not citation numbers", () => {
    // Two claims can be supported by one record. Counting citations would report
    // two resolutions for one fetch and make a shortfall look like a success.
    const repeated: AgentCitation = { ...citation, number: 2 };
    const chain = evidenceChain(REPAIRED_TRACE, [citation, repeated], true, 1);

    expect(chain[3].value).toBe("1 of 1 resolved");
    expect(chain[3].state).toBe("pass");
  });

  it("calls nothing refused while the run is still going", () => {
    // Mid-run the trace holds two receipts and no evidence lookup, and reading that
    // as "returned: none / authorized: refused" told a participant the run had
    // failed while it was still working.
    const midRun = REPAIRED_TRACE.slice(0, 2);
    const chain = evidenceChain(midRun, [], false, null, true);

    expect(chain.map((entry) => entry.state)).toEqual([
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
    expect(chain.map((entry) => entry.value)).toEqual([
      "not yet",
      "not yet",
      "not yet",
      "0 cited, not checked yet",
    ]);
    // The same trace once the run has stopped is a real refusal.
    const settled = evidenceChain(midRun, [], false, null, false);
    expect(settled.map((entry) => entry.state)).toEqual([
      "blocked",
      "pending",
      "blocked",
      "pending",
    ]);
  });

  it("reports no evidence at all when the lookups themselves failed", () => {
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

    expect(chain[0].state).toBe("blocked");
    expect(chain[0].value).toBe("none");
    expect(chain[0].source).toBe("0 successful get_product_evidence calls");
  });
});
