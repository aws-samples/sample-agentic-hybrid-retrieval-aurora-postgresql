// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { mosaicLabManifest } from "../labMissions";
import { showcaseCatalogPage } from "../showcase";
import type { AgentResponse, SearchResponse } from "../types";
import { PlaygroundPage } from "./PlaygroundPage";

vi.mock("./RetrievalLabPage", () => ({ RetrievalLabPage: () => <p>Guide workbench</p> }));
const requests = mosaicLabManifest.playground.requests;
const defaultRequest = requests.find((request) => request.id === mosaicLabManifest.playground.default_request)!;
const callsRequest = requests.find((request) => request.id === "clear-calls")!;
beforeEach(() => {
  window.history.replaceState({}, "", "/labs/retrieval");
  vi.spyOn(api, "readiness").mockRejectedValue(new Error("Offline fixture"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("shows candidate photos as they arrive and replaces them with only the final picks", async () => {
  const products = showcaseCatalogPage({}, 0, 3).products;
  expect(products).toHaveLength(3);
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  const { container } = render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  act(() => emit({ type: "partial", partial: { plan: [], candidates: products, trace: [] } }));
  const candidates = screen.getByRole("region", { name: "Under consideration" });
  expect(candidates.querySelectorAll("img")).toHaveLength(3);
  for (const image of candidates.querySelectorAll("img")) expect(image.getAttribute("src")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  const response: AgentResponse = { agent_run_id: "22222222-2222-4222-8222-222222222222", question: defaultRequest.query, answer: "The final answer.", plan: [], recommendations: [products[1]], citations: [], trace: [] };
  await act(async () => { emit({ type: "complete", response }); finish(); });
  const picks = screen.getByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(picks.querySelectorAll("img")).toHaveLength(1);
  expect(within(picks).getByRole("link").getAttribute("href")).toBe(`/products/${products[1].product_id}`);
  expect(container.querySelector(".inspector-answer")?.getAttribute("aria-busy")).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "Clearer calls" }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Under consideration" })).toBeNull();
});

it("opens on an intent request, offers one Play action, and keeps guide links working", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  expect(screen.getByRole("heading", { name: defaultRequest.query })).toBeTruthy();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.getAllByRole("button", { name: "Play pipeline" })).toHaveLength(1);
  expect(stream).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Clearer calls" }));
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([callsRequest.query, callsRequest.filters]);
  await act(async () => window.history.pushState({}, "", "/labs/retrieval?example=typo-recovery"));
  expect(screen.getByText("Guide workbench")).toBeTruthy();
});

it("shows the actual rank movement from the agent receipt, then clears it when requests change", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  const absent = { rank: null, raw_score: null, rrf_contribution: null };
  const product = { ...showcaseCatalogPage({}, 0, 1).products[0], signals: { fts: absent, trigram: absent, semantic: { ...absent, rank: 27 }, rrf_score: 0.02, pre_rerank_rank: 27, pre_rerank_score: 0.02, rerank_score: 0.9, rerank_rank: 1, final_rank: 1, score_semantics: "fixture" } };
  const response: SearchResponse = { search_event_id: id, query: "agent-selected query", normalized_query: "agent-selected query", applied_filters: {}, results: [product], diagnostics: null };
  const answer: AgentResponse = { agent_run_id: "22222222-2222-4222-8222-222222222222", question: defaultRequest.query, answer: "The recorded answer.", plan: [], recommendations: [product], citations: [], trace: [{ sequence: 1, tool: "search_products", detail: "Actual search", retrieval_run_id: id, result_count: 1, arguments: {}, outcome: "success", latency_ms: 10 }] };
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: answer }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  expect(await screen.findByText(/#27 before rerank/)).toBeTruthy();
  expect(screen.getByText("The recorded answer.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clearer calls" }));
  expect(screen.queryByText(/#27 before rerank/)).toBeNull();
  expect(screen.queryByText("The recorded answer.")).toBeNull();
});
