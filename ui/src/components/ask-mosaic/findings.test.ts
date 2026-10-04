import { describe, expect, it } from "vitest";
import type { AgentCitation, AgentPlanStep, ToolTraceStep } from "../../types";
import { formatDuration, phaseFinding, runSummary, type RunData } from "./findings";

function step(sequence: number, tool: string, overrides: Partial<ToolTraceStep> = {}): ToolTraceStep {
  return {
    sequence,
    tool,
    detail: "",
    retrieval_run_id: null,
    result_count: null,
    arguments: {},
    outcome: "success",
    latency_ms: 10,
    ...overrides,
  };
}

const planned = (category: string, query = category): AgentPlanStep => ({
  query,
  filters: { category_key: category },
  purpose: "Search",
});

const citation = (number: number, type: string): AgentCitation => ({
  number,
  evidence_id: 100 + number,
  evidence_type: type,
  product_id: 1,
  source_uri: "mosaic://x",
  revision: "r1",
  title: "t",
  quote: "q",
});

const run = (overrides: Partial<RunData> = {}): RunData => ({
  path: "full_retrieval",
  plan: [],
  trace: [],
  citations: [],
  ...overrides,
});

describe("phaseFinding", () => {
  it("counts the planned searches and names their categories", () => {
    const data = run({ plan: [planned("headphones"), planned("monitor"), planned("chair")] });
    expect(phaseFinding("understand", data)).toBe("Planned 3 searches: Headphones, Monitor, Chair.");
  });

  it("says nothing before a plan exists, and says the shortlist was reused on a follow-up", () => {
    expect(phaseFinding("understand", run())).toBeNull();
    expect(phaseFinding("understand", run({ path: "focused_follow_up" }))).toBe("Reused the earlier shortlist.");
  });

  it("counts searches and the products they kept from the trace", () => {
    const data = run({
      trace: [
        step(1, "search_products", { result_count: 2 }),
        step(2, "search_products", { result_count: 1 }),
      ],
    });
    expect(phaseFinding("retrieve", data)).toBe("Ran 2 searches in Aurora and kept 3 products.");
  });

  it("does not invent a kept count when a search recorded none", () => {
    const data = run({ trace: [step(1, "search_products")] });
    expect(phaseFinding("retrieve", data)).toBe("Ran 1 search in Aurora.");
    expect(phaseFinding("retrieve", run())).toBeNull();
  });

  it("reports the comparison and the replayed ranking, or their absence", () => {
    const data = run({
      trace: [
        step(1, "compare_products", { arguments: { product_ids: [1, 2, 3] } }),
        step(2, "explain_retrieval"),
      ],
    });
    expect(phaseFinding("rank", data)).toBe("Compared 3 products and replayed the ranking of 1 search.");
    expect(phaseFinding("rank", run())).toBe("No comparison step was recorded.");
  });

  it("splits the citations into listings and reviews", () => {
    const data = run({
      citations: [citation(1, "product_spec"), citation(2, "customer_review"), citation(3, "customer_review")],
      trace: [step(1, "get_product_evidence"), step(2, "get_product_evidence")],
    });
    expect(phaseFinding("answer", data)).toBe(
      "3 citations: 1 from listings and 2 from reviews, after 2 evidence reads.",
    );
    expect(phaseFinding("answer", run())).toBe("No sources were cited.");
  });
});

describe("runSummary", () => {
  it("states steps, searches, sources and time from the same rows", () => {
    const data = run({
      trace: [step(1, "search_products"), step(2, "search_products"), step(3, "search_products")],
      citations: [citation(1, "product_spec")],
    });
    expect(runSummary(data, 43_500)).toBe("4 steps · 3 searches · 1 source · 43.5 s");
  });

  it("leaves the time out when none was measured, and counts a follow-up's three steps", () => {
    expect(runSummary(run({ path: "focused_follow_up" }))).toBe("3 steps · 0 searches · 0 sources");
    expect(formatDuration(1_250)).toBe("1.3 s");
  });
});
