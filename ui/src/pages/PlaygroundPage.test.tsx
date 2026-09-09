// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { mosaicLabManifest } from "../labMissions";
import { showcaseCatalogPage } from "../showcase";
import type { AgentResponse, ProductSummary, SearchResponse, ToolTraceStep } from "../types";
import { PlaygroundPage } from "./PlaygroundPage";

vi.mock("./RetrievalLabPage", () => ({ RetrievalLabPage: () => <p>Guide workbench</p> }));
const requests = mosaicLabManifest.playground.requests;
const defaultRequest = requests.find((request) => request.id === mosaicLabManifest.playground.default_request)!;
const callsRequest = requests.find((request) => request.id === "clear-calls")!;
const originalScrollIntoView = Element.prototype.scrollIntoView;
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  window.history.replaceState({}, "", "/labs/retrieval");
  vi.spyOn(api, "readiness").mockRejectedValue(new Error("Offline fixture"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); Element.prototype.scrollIntoView = originalScrollIntoView; });

const firstSearchId = "11111111-1111-4111-8111-111111111111";
const secondSearchId = "22222222-2222-4222-8222-222222222222";
const agentId = "33333333-3333-4333-8333-333333333333";
function ranked(product: ProductSummary, before: number, final: number): ProductSummary {
  const absent = { rank: null, raw_score: null, rrf_contribution: null };
  return { ...product, signals: { fts: absent, trigram: absent, semantic: absent, rrf_score: 0.02, pre_rerank_rank: before, pre_rerank_score: 0.02, rerank_score: 0.9, rerank_rank: final, final_rank: final, score_semantics: "fixture" } };
}
const savedSearch = (id: string, products: ProductSummary[]): SearchResponse => ({ search_event_id: id, query: `Saved query ${id}`, normalized_query: "saved", applied_filters: { category_key: "over-ear-headphones", max_price_cents: 20000 }, results: products, diagnostics: null });
const searchStep = (id: string, sequence: number): ToolTraceStep => ({ sequence, tool: "search_products", detail: "Saved search", retrieval_run_id: id, result_count: 2, arguments: {}, outcome: "success", latency_ms: 10 });
const productLinks = (region: HTMLElement) => within(region).getAllByRole("link").map((link) => link.getAttribute("href"));

it("replays Shop's saved results with the same preview products, then explicitly starts a new run and can return", async () => {
  const products = showcaseCatalogPage({}, 0, 4).products.map((product, index) => ranked(product, [7, 5, 9, 1][index], index + 1));
  const original = savedSearch(firstSearchId, products);
  window.history.replaceState({}, "", `/labs/retrieval?event=${firstSearchId}&q=Different+URL+words&category=quiet-keyboards`);
  const replay = vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => id === firstSearchId ? original : savedSearch(secondSearchId, [products[3]]));
  const search = vi.spyOn(api, "search");
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: original.query, answer: "A new recommendation.", plan: [], recommendations: [products[3]], citations: [], trace: [searchStep(secondSearchId, 1)] } }));
  render(<PlaygroundPage />);
  await screen.findByRole("heading", { name: original.query });
  expect(stream).not.toHaveBeenCalled();
  expect(search).not.toHaveBeenCalled();
  const retrieve = screen.getByRole("list", { name: "Retrieved product preview" });
  const rank = screen.getByRole("list", { name: "Final ranking preview" });
  expect(productLinks(retrieve)).toEqual([products[1], products[0], products[2]].map((product) => `/products/${product.product_id}`));
  expect(productLinks(rank)).toEqual(products.slice(0, 3).map((product) => `/products/${product.product_id}`));
  for (const link of within(retrieve).getAllByRole("link")) {
    const matching = within(rank).getAllByRole("link").find((item) => item.getAttribute("href") === link.getAttribute("href"));
    expect(link.querySelector("img")?.getAttribute("src")).toBe(matching?.querySelector("img")?.getAttribute("src"));
  }
  expect(screen.getByLabelText("#7 before rerank, #1 in the final order")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(within(screen.getByRole("region", { name: "Product ranking details" })).getAllByRole("listitem")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Start a new run" }));
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([original.query, original.applied_filters]);
  expect(screen.getByRole("heading", { name: original.query })).toBeTruthy();
  expect(screen.getByText(/This is a new run/)).toBeTruthy();
  const back = screen.getByRole("button", { name: "Back to saved Shop results" });
  await waitFor(() => expect((back as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(back);
  await waitFor(() => expect(productLinks(screen.getByRole("list", { name: "Final ranking preview" }))).toEqual(products.slice(0, 3).map((product) => `/products/${product.product_id}`)));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(stream).toHaveBeenCalledTimes(1);
  expect(replay.mock.calls.map(([id]) => id)).toEqual([firstSearchId, secondSearchId, firstSearchId]);
});

it("shows every recommendation, follows its recorded search, and preserves a chosen search as the answer finishes", async () => {
  const products = showcaseCatalogPage({}, 0, 4).products;
  const first = savedSearch(firstSearchId, [ranked(products[0], 3, 1), ranked(products[1], 45, 2)]);
  const second = savedSearch(secondSearchId, [ranked(products[2], 43, 1), ranked(products[3], 16, 2), ranked(products[1], 5, 3)]);
  const answer: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: "Picks across two searches.", plan: [], recommendations: [products[2], products[3], products[0], products[1]], citations: [], trace: [searchStep(firstSearchId, 1), searchStep(secondSearchId, 2)] };
  vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => id === firstSearchId ? first : second);
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => { emit = callback; await new Promise<void>((resolve) => { finish = resolve; }); });
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  await act(async () => emit({ type: "answer_start", response: answer }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  const selector = screen.getByRole("combobox", { name: "Search shown in Retrieve and Rank" }) as HTMLSelectElement;
  expect(selector.value).toBe(firstSearchId);
  expect(productLinks(screen.getByRole("list", { name: "Final ranking preview" }))).toEqual(first.results.map((product) => `/products/${product.product_id}`));
  fireEvent.change(selector, { target: { value: firstSearchId } });
  await act(async () => { emit({ type: "complete", response: answer }); finish(); });
  expect(selector.value).toBe(firstSearchId);
  const picks = screen.getByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(productLinks(picks)).toEqual(answer.recommendations.map((product) => `/products/${product.product_id}`));
  expect(picks.querySelectorAll("ol > li")).toHaveLength(4);
  expect(picks.querySelectorAll("img")).toHaveLength(4);
  fireEvent.click(within(picks).getByRole("button", { name: `${products[0].title}: show Search 1, rank 1` }));
  expect(selector.value).toBe(firstSearchId);
  expect(document.activeElement?.id).toBe(`ranked-product-${products[0].product_id}`);
  expect(screen.getByRole("region", { name: "Product ranking details" })).toBeTruthy();
  expect(within(picks).getByRole("button", { name: `${products[1].title}: show Search 1, rank 2` })).toBeTruthy();
  expect(within(picks).getByRole("button", { name: `${products[1].title}: show Search 2, rank 3` })).toBeTruthy();
  fireEvent.click(within(picks).getByRole("button", { name: `${products[3].title}: show Search 2, rank 2` }));
  expect(selector.value).toBe(secondSearchId);
  expect(document.activeElement?.id).toBe(`ranked-product-${products[3].product_id}`);
});

it("keeps a recommendation visible when its search is delayed or unavailable without inventing a source", async () => {
  const product = showcaseCatalogPage({}, 0, 1).products[0];
  let reject!: (cause: Error) => void;
  vi.spyOn(api, "retrievalEventResponse").mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "An answer whose search is unavailable.", plan: [], recommendations: [product], citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  const picks = await screen.findByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(within(picks).getByText("Loading this product’s search…")).toBeTruthy();
  expect(within(picks).queryByRole("button")).toBeNull();
  await act(async () => reject(new Error("Saved record unavailable")));
  expect(within(picks).getByText("This product’s search details could not be loaded.")).toBeTruthy();
  expect(within(picks).getByRole("link").getAttribute("href")).toBe(`/products/${product.product_id}`);
  expect(within(picks).queryByRole("button")).toBeNull();
});

it("does not start from URL filters when a saved Shop record cannot be loaded", async () => {
  window.history.replaceState({}, "", `/labs/retrieval?event=${firstSearchId}&q=Unverified+request`);
  vi.spyOn(api, "retrievalEventResponse").mockRejectedValue(new Error("Record unavailable"));
  const stream = vi.spyOn(api, "agentStream");
  render(<PlaygroundPage />);
  await screen.findByRole("alert");
  const play = screen.getByRole("button", { name: "Start a new run" }) as HTMLButtonElement;
  expect(play.disabled).toBe(true);
  fireEvent.click(play);
  expect(stream).not.toHaveBeenCalled();
});

it("streams the full answer above the cards and waits for its final recommendation order", async () => {
  const products = showcaseCatalogPage({}, 0, 3).products;
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  const { container } = render(<PlaygroundPage />);
  const reason = screen.getByRole("region", { name: "Reason" });
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  act(() => emit({ type: "partial", partial: { plan: [], candidates: products, trace: [] } }));
  expect(reason.querySelectorAll("img")).toHaveLength(0);
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  act(() => emit({ type: "stage", id: "answer", path: "full_retrieval", title: "Answer", detail: "Synthesis" }));
  expect(within(reason).getByText(/Comparing 3 products/)).toBeTruthy();
  expect(reason.querySelector(".inspector-reason-status svg.spin")).toBeTruthy();
  const response: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: `${products[1].title} is the best fit. ${"Full supporting explanation. ".repeat(30)}The final sentence.`, plan: [], recommendations: [products[1], products[0]], citations: [], trace: [] };
  act(() => emit({ type: "answer_start", response: { ...response, answer: "" } }));
  act(() => emit({ type: "answer_delta", delta: `${products[1].title} is the best fit.` }));
  expect(within(reason).getByText(`${products[1].title} is the best fit.`)).toBeTruthy();
  expect(reason.querySelectorAll("img")).toHaveLength(0);
  expect(container.querySelector(".inspector-answer")?.getAttribute("aria-busy")).toBe("true");
  await act(async () => { emit({ type: "complete", response }); finish(); });
  const picks = screen.getByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(productLinks(picks)).toEqual([products[1], products[0]].map((product) => `/products/${product.product_id}`));
  const prose = reason.querySelector(".inspector-answer")!;
  expect(prose.textContent).toContain("The final sentence.");
  expect(prose.compareDocumentPosition(picks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(prose.getAttribute("aria-busy")).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "Quiet typing" }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(container.querySelector(".inspector-answer")).toBeNull();
});

it("follows the live stages left to right and returns to Retrieve for a second search", async () => {
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  render(<PlaygroundPage />);
  const retrieve = screen.getByRole("region", { name: "Retrieve" });
  const rank = screen.getByRole("region", { name: "Rank" });
  const reason = screen.getByRole("region", { name: "Reason" });
  const states = () => [retrieve, rank, reason].map((column) => column.dataset.state);
  expect(states()).toEqual(["idle", "idle", "idle"]);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  expect(states()).toEqual(["active", "pending", "pending"]);
  expect(within(retrieve).getByRole("status", { name: "Retrieve: working" }).querySelector("svg.spin")).toBeTruthy();
  for (const [id, expected] of [["rank", ["complete", "active", "pending"]], ["answer", ["complete", "complete", "active"]], ["retrieve", ["active", "pending", "pending"]]] as const) {
    act(() => emit({ type: "stage", id, path: "full_retrieval", title: id, detail: id }));
    expect(states()).toEqual(expected);
    expect(document.querySelectorAll('.inspector-column[aria-current="step"]')).toHaveLength(1);
  }
  await act(async () => {
    emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "Finished.", plan: [], recommendations: [], citations: [], trace: [] } });
    finish();
  });
  expect(states()).toEqual(["complete", "complete", "complete"]);
  expect(document.querySelectorAll('.inspector-column[aria-current="step"]')).toHaveLength(0);
});

it("keeps each detail panel inside its column and lets all three stay open", async () => {
  const products = showcaseCatalogPage({}, 0, 2).products.map((product, index) => ranked(product, index + 4, index + 1));
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(savedSearch(firstSearchId, products));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The recorded answer.", plan: [], recommendations: products, citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  await screen.findByRole("list", { name: "Final ranking preview" });
  for (const [column, label] of [["Retrieve", "Search details"], ["Rank", "Why the order changed"], ["Reason", "Answer and sources"]]) {
    const region = screen.getByRole("region", { name: column });
    fireEvent.click(within(region).getByRole("button", { name: label }));
    expect(region.contains(screen.getByRole("region", { name: label }))).toBe(true);
  }
  expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(screen.queryByRole("region", { name: "Why the order changed" })).toBeNull();
  expect(screen.getByRole("region", { name: "Search details" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Answer and sources" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: `${products[0].title}: show Search 1, rank 1` }));
  expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(3);
  expect(document.activeElement?.id).toBe(`ranked-product-${products[0].product_id}`);
});

it("opens on Clearer calls, offers one Play action, and keeps guide links working", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  expect(screen.getByRole("heading", { name: callsRequest.query })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Clearer calls" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.getAllByRole("button", { name: "Play pipeline" })).toHaveLength(1);
  expect(stream).not.toHaveBeenCalled();
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
  expect(await screen.findByLabelText("#27 before rerank, #1 in the final order")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(await screen.findByText(/#27 before rerank/)).toBeTruthy();
  expect(screen.getByRole("region", { name: "Product ranking details" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Why the order changed" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("The recorded answer.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Quiet typing" }));
  expect(screen.queryByText(/#27 before rerank/)).toBeNull();
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  expect(screen.queryByText("The recorded answer.")).toBeNull();
});

it("runs the canonical multi-part request from the new Pipeline choice", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Plan my workspace" }));
  const mission = mosaicLabManifest.missions.find((item) => item.id === "agentic-research")!;
  expect(screen.getByRole("heading", { name: mission.query })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([mission.query, mission.filters]);
});

it("keeps old coding-guide URLs on the participant Playground without starting an agent", () => {
  window.history.replaceState({}, "", "/labs/retrieval?view=build");
  const stream = vi.spyOn(api, "agentStream");
  render(<PlaygroundPage />);
  expect(screen.getByRole("heading", { name: "Behind a better answer." })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Build a retrieval tool" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Download code & guide" })).toBeNull();
  expect(stream).not.toHaveBeenCalled();
});

it("keeps the first search counts when a later search supplies the leading recommendation", async () => {
  const products = showcaseCatalogPage({}, 0, 2).products;
  const withCounts = (id: string, product: ProductSummary, counts: number[]) => ({
    ...savedSearch(id, [product]),
    diagnostics: { candidate_counts: { fts_in_pool: counts[0], trigram_in_pool: counts[1], semantic_in_pool: counts[2] } } as unknown as SearchResponse["diagnostics"],
  });
  const first = withCounts(firstSearchId, products[0], [4, 4, 46]);
  const second = withCounts(secondSearchId, products[1], [0, 0, 50]);
  vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => id === firstSearchId ? first : second);
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => { emit = callback; await new Promise<void>((resolve) => { finish = resolve; }); });
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Play pipeline" }));
  const answer: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: "Completed.", plan: [], recommendations: [products[0]], citations: [], trace: [searchStep(firstSearchId, 1)] };
  await act(async () => emit({ type: "answer_start", response: answer }));
  const visibleCounts = () => [...document.querySelectorAll(".inspector-arm-counts dd")].map((node) => node.textContent);
  expect(visibleCounts()).toEqual(["4", "4", "46"]);
  await act(async () => { emit({ type: "complete", response: { ...answer, recommendations: [products[1]], trace: [...answer.trace, searchStep(secondSearchId, 2)] } }); finish(); });
  expect(visibleCounts()).toEqual(["4", "4", "46"]);
  const selector = screen.getByRole("combobox", { name: "Search shown in Retrieve and Rank" });
  fireEvent.change(selector, { target: { value: secondSearchId } });
  expect(visibleCounts()).toEqual(["0", "0", "50"]);
});
