// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { SearchResponse, ToolTraceStep } from "../../types";
import { RunSteps, agentChips, searchChips } from "./RunSteps";

afterEach(cleanup);

const response = (rerank: "applied" | "disabled") => ({
  results: new Array(12).fill(null),
  diagnostics: {
    rerank_status: rerank,
    candidate_counts: { fts_in_pool: 3, trigram_in_pool: 0, semantic_in_pool: 42, fused_pool: 50 },
    stage_timings_ms: { postgresql_retrieval: 161.4, rerank: 1827 },
  },
}) as unknown as SearchResponse;

const step = (sequence: number, tool: string, outcome: ToolTraceStep["outcome"], latency: number | null): ToolTraceStep => ({
  sequence, tool, outcome, latency_ms: latency, detail: tool, retrieval_run_id: null, result_count: null, arguments: {},
});

it("reads a search as the pipeline ran it, from its own counts and timings", () => {
  const chips = searchChips(response("applied"));
  expect(chips.map((chip) => [chip.label, chip.value ?? "", chip.state])).toEqual([
    ["Full-text search", "3", "done"],
    ["Fuzzy matching", "0", "quiet"],
    ["Semantic search", "42", "done"],
    ["Combined in Aurora", "50 · 161 ms", "done"],
    ["Reranked", "1.8 s", "done"],
    ["Shown", "12", "done"],
  ]);
});

it("says a search was not reranked rather than showing a time it does not have", () => {
  const rerank = searchChips(response("disabled")).find((chip) => chip.key === "rerank");
  expect(rerank).toMatchObject({ label: "Not reranked", value: undefined, state: "quiet" });
});

it("names each tool call in plain words and keeps denied apart from failed", () => {
  const chips = agentChips([
    step(1, "search_products", "success", 412),
    step(2, "search_products", "error", null),
    step(3, "synthesize_cited_answer", "denied", 90),
  ], "reason", true);
  expect(chips.map((chip) => [chip.label, chip.state])).toEqual([
    ["Search", "done"], ["Search", "failed"], ["Write cited answer", "quiet"], ["Writing the answer", "running"],
  ]);
});

it("draws the chips as one labelled list with arrows between the pipeline's stages", () => {
  render(<RunSteps chips={searchChips(response("applied"))} label="How this search ran" />);
  const list = screen.getByRole("list", { name: "How this search ran" });
  expect(within(list).getByText("Semantic search").closest(".pg-chip")?.getAttribute("data-state")).toBe("done");
  expect(list.querySelectorAll(".pg-chip-then")).toHaveLength(3);
});
