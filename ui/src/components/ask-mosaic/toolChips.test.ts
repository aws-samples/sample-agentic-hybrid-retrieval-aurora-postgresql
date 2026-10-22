import { describe, expect, it } from "vitest";
import type { ToolTraceStep } from "../../types";
import { toolChips, toolName } from "./toolChips";

const step = (sequence: number, tool: string, overrides: Partial<ToolTraceStep> = {}): ToolTraceStep => ({
  sequence, tool, detail: "", retrieval_run_id: null, result_count: null,
  arguments: {}, outcome: "success", latency_ms: 312.5, ...overrides,
});

describe("toolName", () => {
  it("names each tool in plain words", () => {
    expect(["get_product_evidence", "compare_products", "explain_retrieval", "synthesize_cited_answer"]
      .map((tool) => toolName(step(1, tool)))).toEqual(["Read sources", "Compare", "Explain ranking", "Write cited answer"]);
  });

  it("adds a short query to a search, else its category, else nothing", () => {
    expect(toolName(step(1, "search_products", { arguments: { query: "quiet headphones" } }))).toBe("Search quiet headphones");
    const long = "x".repeat(40);
    expect(toolName(step(1, "search_products", { arguments: { query: long, category_key: "monitor" } }))).toBe("Search Monitor");
    expect(toolName(step(1, "search_products", { arguments: { query: long } }))).toBe("Search");
  });
});

describe("toolChips", () => {
  it("maps outcomes to states and keeps a time that was not recorded null", () => {
    const chips = toolChips(
      [step(1, "search_products"), step(2, "compare_products", { outcome: "error", latency_ms: null }), step(3, "explain_retrieval", { outcome: "denied" })],
    );
    expect(chips.map((chip) => chip.state)).toEqual(["done", "failed", "denied"]);
    expect(chips.map((chip) => chip.latencyMs)).toEqual([312.5, null, 312.5]);
  });

  it("keeps each tool's own name beside its plain label, as the terminal prints it", () => {
    const chips = toolChips([step(1, "search_products"), step(2, "get_product_evidence")]);
    expect(chips.map((chip) => [chip.label, chip.tool])).toEqual([
      ["Search", "search_products"],
      ["Read sources", "get_product_evidence"],
    ]);
  });

  it("lists no chip before a tool call was recorded", () => {
    expect(toolChips([])).toEqual([]);
  });
});
