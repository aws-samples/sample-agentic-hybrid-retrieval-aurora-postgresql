import { describe, expect, it } from "vitest";
import type { AgentPlanStep, AgentResponse, ToolTraceStep } from "../../types";
import { NOT_RECORDED, formatArguments, runFacts, stepsFor } from "./builderModel";

function step(sequence: number, tool: string, overrides: Partial<ToolTraceStep> = {}): ToolTraceStep {
  return {
    sequence,
    tool,
    detail: "Retrieved a bounded set.",
    retrieval_run_id: null,
    result_count: null,
    arguments: {},
    outcome: "success",
    origin: "model",
    latency_ms: 3880,
    ...overrides,
  };
}

const plan: AgentPlanStep[] = [
  { query: "Steelcase Gesture chair", filters: { category_key: "chair" }, purpose: "Search" },
  { query: "ViewSonic VG2756-4K monitor", filters: {}, purpose: "Search" },
];

describe("stepsFor", () => {
  it("builds the request phase from the plan and puts each tool in its own phase", () => {
    const trace = [
      step(1, "search_products", { result_count: 2, retrieval_run_id: "cc3a32d8-1111", arguments: { query: "chair", limit: 2 } }),
      step(2, "compare_products"),
      step(3, "explain_retrieval"),
      step(4, "get_product_evidence"),
      step(5, "synthesize_cited_answer"),
    ];
    expect(stepsFor("understand", plan, trace).map((item) => item.tool)).toEqual(["plan"]);
    expect(stepsFor("retrieve", plan, trace).map((item) => item.tool)).toEqual(["search_products"]);
    expect(stepsFor("rank", plan, trace).map((item) => item.tool)).toEqual(["compare_products", "explain_retrieval"]);
    expect(stepsFor("answer", plan, trace).map((item) => item.tool)).toEqual([
      "get_product_evidence",
      "synthesize_cited_answer",
    ]);
  });

  it("prints count, time and run id, the arguments and the origin and outcome", () => {
    const [search] = stepsFor("retrieve", [], [
      step(1, "search_products", { result_count: 2, retrieval_run_id: "cc3a32d8-1111", arguments: { query: "chair", limit: 2 } }),
    ]);
    expect(search.meta).toBe("2 results · 3.9 s · cc3a32d8");
    expect(search.args).toBe('query="chair" limit=2');
    expect(search.tags.map((tag) => tag.label)).toEqual([
      "Aurora search",
      "Combine and rerank",
      "Requested by the model",
      "Step completed",
    ]);
  });

  it("marks a failed application-started step, in words and with a problem dot", () => {
    const [failed] = stepsFor("answer", [], [
      step(1, "get_product_evidence", { origin: "controller_fallback", outcome: "error" }),
    ]);
    const labels = failed.tags.map((tag) => tag.label);
    expect(labels).toContain("Started by the application");
    expect(labels).toContain("Step failed");
    expect(failed.tags.find((tag) => tag.label === "Step failed")?.stage).toBe("problem");
  });

  it("files an unknown tool under the last phase instead of dropping it", () => {
    expect(stepsFor("answer", [], [step(1, "brand_new_tool")]).map((item) => item.tool)).toEqual(["brand_new_tool"]);
  });

  it("names the plan's searches with their categories", () => {
    const [planned] = stepsFor("understand", plan, []);
    expect(planned.meta).toBe("2 searches");
    expect(planned.args).toBe('"Steelcase Gesture chair" Chair · "ViewSonic VG2756-4K monitor"');
  });

  it("formats arguments as key=value", () => {
    expect(formatArguments({ product_ids: [1, 2], category: "chair" })).toBe('product_ids=[1,2] category="chair"');
  });
});

describe("runFacts", () => {
  const response = {
    agent_run_id: "fc97f09b-0000-4000-8000-000000000000",
    session_id: "ed17ba76-0000-4000-8000-000000000000",
    outcome: "grounded",
    memory: { enabled: false },
  } as unknown as AgentResponse;

  it("states the run, session, outcome, time and memory", () => {
    expect(runFacts(response, 43_500)).toEqual([
      "run fc97f09b",
      "session ed17ba76",
      "grounded",
      "43.5 s",
      "memory off",
    ]);
  });

  it("leaves out a session or a time the response does not carry", () => {
    expect(runFacts({ ...response, session_id: null, memory: { enabled: true } } as unknown as AgentResponse)).toEqual([
      "run fc97f09b",
      "grounded",
      "memory on",
    ]);
  });

  it("lists the four things the response has no field for", () => {
    expect(NOT_RECORDED).toEqual(["model id", "tokens", "Gateway target", "claim verdicts"]);
  });
});
