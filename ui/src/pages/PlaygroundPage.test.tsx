// @vitest-environment jsdom
import { pipelineRequests } from "../labMissions";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs, mosaicLabManifest } from "../labMissions";
import { fixtureCatalogPage } from "../testProducts";
import type { AgentResponse, EvidenceRecord, LabStateRecord, ProductSummary, RetrievalScorecardResponse, ScorecardStageArm, SearchResponse, ToolTraceStep } from "../types";
import { PlaygroundPage } from "./PlaygroundPage";

vi.mock("./RetrievalLabPage", () => ({ RetrievalLabPage: () => <p>Guide workbench</p> }));
const requests = pipelineRequests;
const defaultRequest = requests.find((request) => request.id === mosaicLabManifest.playground.default_request)!;
const callsRequest = requests.find((request) => request.id === "focus-at-home")!;
const originalScrollIntoView = Element.prototype.scrollIntoView;
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  window.history.replaceState({}, "", "/labs/retrieval");
  vi.spyOn(api, "readiness").mockRejectedValue(new Error("Offline fixture"));
  vi.spyOn(api, "scorecard").mockRejectedValue(new Error("Offline fixture"));
  vi.spyOn(api, "labsState").mockRejectedValue(new Error("Offline fixture"));
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

it("opens a saved Shop search in the pipeline layout even when the link carries a lab example", async () => {
  const response = savedSearch(firstSearchId, [ranked(fixtureCatalogPage({}, 0, 1).products[0], 2, 1)]);
  window.history.replaceState({}, "", `/labs/retrieval?q=B0C2WWFCQB&event=${firstSearchId}&example=typo-recovery#labs-stage-re-rank`);
  const replay = vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  const search = vi.spyOn(api, "search");
  const stream = vi.spyOn(api, "agentStream");
  render(<PlaygroundPage />);
  expect(screen.queryByText("Guide workbench")).toBeNull();
  await screen.findByRole("heading", { name: response.query });
  expect(screen.getByRole("button", { name: "Why the order changed" }).getAttribute("aria-expanded")).toBe("true");
  expect(replay).toHaveBeenCalledWith(firstSearchId);
  expect(search).not.toHaveBeenCalled();
  expect(stream).not.toHaveBeenCalled();
  const details = screen.getByRole("link", { name: "Open lab details" });
  const params = new URL(details.getAttribute("href")!, "https://mosaic.invalid").searchParams;
  expect(params.get("view")).toBe("lab");
  expect(params.get("event")).toBe(firstSearchId);
  expect(params.get("example")).toBe("typo-recovery");
  fireEvent.click(details);
  expect(await screen.findByText("Guide workbench")).toBeTruthy();
  expect(search).not.toHaveBeenCalled();
  expect(stream).not.toHaveBeenCalled();
});

it.each([
  "example=typo-recovery",
  `view=lab&event=${firstSearchId}&example=typo-recovery`,
  `example=agentic-research&run=${agentId}`,
])("preserves explicit lab and agent-proof links: %s", (query) => {
  window.history.replaceState({}, "", `/labs/retrieval?${query}`);
  render(<PlaygroundPage />);
  expect(screen.getByText("Guide workbench")).toBeTruthy();
});

it("replays Shop's saved results with the same preview products, then explicitly starts a new run and can return", async () => {
  const products = fixtureCatalogPage({}, 0, 4).products.map((product, index) => ranked(product, [7, 5, 9, 1][index], index + 1));
  const original = savedSearch(firstSearchId, products);
  window.history.replaceState({}, "", `/labs/retrieval?event=${firstSearchId}&q=Different+URL+words&category=quiet-keyboards`);
  const replay = vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => id === firstSearchId ? original : savedSearch(secondSearchId, [products[3]]));
  const search = vi.spyOn(api, "search");
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: original.query, answer: "A new recommendation.", plan: [], recommendations: [products[3]], citations: [], trace: [searchStep(secondSearchId, 1)] } }));
  render(<PlaygroundPage />);
  await screen.findByRole("heading", { name: original.query });
  expect(stream).not.toHaveBeenCalled();
  expect(search).not.toHaveBeenCalled();
  const finalSources = new Map(within(screen.getByRole("list", { name: "Final ranking preview" })).getAllByRole("link").map((link) => [link.getAttribute("href"), link.querySelector("img")?.getAttribute("src")]));
  expect([...finalSources.keys()]).toEqual(products.map((product) => `/products/${product.product_id}`));
  fireEvent.click(screen.getByRole("button", { name: "Before reranking (displayed products)" }));
  const retrieve = screen.getByRole("list", { name: "Retrieved product preview" });
  expect(productLinks(retrieve)).toEqual([products[3], products[1], products[0], products[2]].map((product) => `/products/${product.product_id}`));
  for (const link of within(retrieve).getAllByRole("link")) {
    expect(link.querySelector("img")?.getAttribute("src")).toBe(finalSources.get(link.getAttribute("href")));
  }
  fireEvent.click(screen.getByRole("button", { name: "Final order" }));
  expect(screen.getByLabelText("#7 before rerank, #1 in the final order")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(within(screen.getByRole("region", { name: "Product ranking details" })).getAllByRole("listitem")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([original.query, original.applied_filters]);
  expect(screen.getByRole("heading", { name: original.query })).toBeTruthy();
  expect(screen.getByText(/This is a new run/)).toBeTruthy();
  const back = screen.getByRole("button", { name: "Back to saved Shop results" });
  await waitFor(() => expect((back as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(back);
  await waitFor(() => expect(productLinks(screen.getByRole("list", { name: "Final ranking preview" }))).toEqual(products.map((product) => `/products/${product.product_id}`)));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(stream).toHaveBeenCalledTimes(1);
  expect(replay.mock.calls.map(([id]) => id)).toEqual([firstSearchId, secondSearchId, firstSearchId]);
});

it("shows every recommendation, follows its recorded search, and preserves a chosen search as the answer finishes", async () => {
  const products = fixtureCatalogPage({}, 0, 4).products;
  const first = savedSearch(firstSearchId, [ranked(products[0], 3, 1), ranked(products[1], 45, 2)]);
  const second = savedSearch(secondSearchId, [ranked(products[2], 43, 1), ranked(products[3], 16, 2), ranked(products[1], 5, 3)]);
  const answer: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: "Picks across two searches.", plan: [], recommendations: [products[2], products[3], products[0], products[1]], citations: [], trace: [searchStep(firstSearchId, 1), searchStep(secondSearchId, 2)] };
  vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => id === firstSearchId ? first : second);
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => { emit = callback; await new Promise<void>((resolve) => { finish = resolve; }); });
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await act(async () => emit({ type: "answer_start", response: answer }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  const selector = screen.getByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" }) as HTMLSelectElement;
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
  const product = fixtureCatalogPage({}, 0, 1).products[0];
  let reject!: (cause: Error) => void;
  vi.spyOn(api, "retrievalEventResponse").mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "An answer whose search is unavailable.", plan: [], recommendations: [product], citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
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
  const play = screen.getByRole("button", { name: "Ask about this need" }) as HTMLButtonElement;
  expect(play.disabled).toBe(true);
  fireEvent.click(play);
  expect(stream).not.toHaveBeenCalled();
});

it("streams the full answer, then keeps all of it in view above every pick", async () => {
  const products = fixtureCatalogPage({}, 0, 3).products;
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  const { container } = render(<PlaygroundPage />);
  const reason = screen.getByRole("region", { name: "Reason" });
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  act(() => emit({ type: "partial", partial: { plan: [], candidates: products, trace: [] } }));
  expect(reason.querySelectorAll("img")).toHaveLength(0);
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  act(() => emit({ type: "stage", id: "answer", path: "full_retrieval", title: "Answer", detail: "Synthesis" }));
  expect(within(reason).getByText(/Comparing 3 products/)).toBeTruthy();
  expect(reason.querySelector(".pg-reason-status svg.spin")).toBeTruthy();
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
  expect(prose.closest("details")).toBeNull();
  expect(prose.compareDocumentPosition(picks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(prose.getAttribute("aria-busy")).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "More screen space" }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(container.querySelector(".inspector-answer")).toBeNull();
});

it("does not infer completed retrieval phases from agent comparison events", async () => {
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  render(<PlaygroundPage />);
  const stages = ["Retrieve", "Rank", "Re-rank", "Reason"].map((name) => screen.getByRole("region", { name }));
  const states = () => stages.map((column) => column.dataset.state);
  expect(states()).toEqual(["idle", "idle", "idle", "idle"]);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  for (const id of ["rank", "answer", "retrieve"] as const) {
    act(() => emit({ type: "stage", id, path: "full_retrieval", title: id, detail: id }));
    expect(states()).toEqual(["pending", "pending", "pending", "active"]);
  }
  await act(async () => {
    emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "Finished.", plan: [], recommendations: [], citations: [], trace: [] } });
    finish();
  });
  expect(states()).toEqual(["idle", "idle", "idle", "complete"]);
});

it.each([
  ["retrieve", ["blocked", "blocked", "failed"]],
  ["rank", ["blocked", "blocked", "failed"]],
  ["answer", ["blocked", "blocked", "failed"]],
] as const)("ends waiting states after a failure at %s and supports retry", async (id, expected) => {
  const stream = vi.spyOn(api, "agentStream").mockImplementationOnce(async (_question, _filters, emit) => {
    emit({ type: "stage", id, path: "full_retrieval", title: id, detail: id });
    throw new Error("Catalog connection unavailable.");
  });
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await screen.findByRole("alert");
  const regions = ["Retrieve", "Rank", "Reason"].map((name) => screen.getByRole("region", { name }));
  expect(regions.map((region) => region.dataset.state)).toEqual(expected);
  expect(screen.queryByRole("status", { name: /waiting|working/ })).toBeNull();
  expect(screen.queryByText("Matching products will appear as the search finishes.")).toBeNull();
  expect(screen.getByText("No search results are available from this run.")).toBeTruthy();
  stream.mockImplementationOnce(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "Recovered.", plan: [], recommendations: [], citations: [], trace: [] } }));
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await screen.findByText("Recovered.");
  expect(regions.map((region) => region.dataset.state)).toEqual(["idle", "idle", "complete"]);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps each detail panel inside its column and lets all three stay open", async () => {
  const products = fixtureCatalogPage({}, 0, 2).products.map((product, index) => ranked(product, index + 4, index + 1));
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(savedSearch(firstSearchId, products));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The recorded answer.", plan: [], recommendations: products, citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await screen.findByRole("list", { name: "Final ranking preview" });
  for (const [column, label] of [["Retrieve", "Search details"], ["Rank", "Fusion details"], ["Re-rank", "Why the order changed"], ["Reason", "Steps and sources"]]) {
    const region = screen.getByRole("region", { name: column });
    fireEvent.click(within(region).getByRole("button", { name: label }));
    expect(region.contains(screen.getByRole("region", { name: label }))).toBe(true);
  }
  expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(screen.queryByRole("region", { name: "Why the order changed" })).toBeNull();
  expect(screen.getByRole("region", { name: "Search details" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Steps and sources" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: `${products[0].title}: show Search 1, rank 1` }));
  expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(4);
  expect(document.activeElement?.id).toBe(`ranked-product-${products[0].product_id}`);
});

it("opens on Clearer calls, offers one Play action, and keeps guide links working", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  expect(screen.getByRole("heading", { name: callsRequest.query })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Focus at home" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.getAllByRole("button", { name: "Ask about this need" })).toHaveLength(1);
  expect(stream).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([callsRequest.query, callsRequest.filters]);
  await act(async () => window.history.pushState({}, "", "/labs/retrieval?example=typo-recovery"));
  expect(screen.getByText("Guide workbench")).toBeTruthy();
});

it("shows the actual rank movement from the agent receipt, then clears it when requests change", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  const absent = { rank: null, raw_score: null, rrf_contribution: null };
  const product = { ...fixtureCatalogPage({}, 0, 1).products[0], signals: { fts: absent, trigram: absent, semantic: { ...absent, rank: 27 }, rrf_score: 0.02, pre_rerank_rank: 27, pre_rerank_score: 0.02, rerank_score: 0.9, rerank_rank: 1, final_rank: 1, score_semantics: "fixture" } };
  const response: SearchResponse = { search_event_id: id, query: "agent-selected query", normalized_query: "agent-selected query", applied_filters: {}, results: [product], diagnostics: null };
  const answer: AgentResponse = { agent_run_id: "22222222-2222-4222-8222-222222222222", question: defaultRequest.query, answer: "The recorded answer.", plan: [], recommendations: [product], citations: [], trace: [{ sequence: 1, tool: "search_products", detail: "Actual search", retrieval_run_id: id, result_count: 1, arguments: {}, outcome: "success", latency_ms: 10 }] };
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: answer }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  expect(await screen.findByLabelText("#27 before rerank, #1 in the final order")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Why the order changed" }));
  expect(await screen.findByRole("region", { name: "Product ranking details" })).toBeTruthy();
  expect(screen.getAllByLabelText("#27 before rerank, #1 in the final order")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Why the order changed" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("The recorded answer.")).toBeTruthy();
  expect(screen.getByText("One of the agent’s picks.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "More screen space" }));
  expect(screen.queryByLabelText("#27 before rerank, #1 in the final order")).toBeNull();
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  expect(screen.queryByText("The recorded answer.")).toBeNull();
});

it("runs the canonical multi-part request from the new Pipeline choice", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Complete my room" }));
  const mission = mosaicLabManifest.missions.find((item) => item.id === "agentic-research")!;
  expect(screen.getByRole("heading", { name: mission.query })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Run Mosaic" }));
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
  const products = fixtureCatalogPage({}, 0, 2).products;
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
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  const answer: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: "Completed.", plan: [], recommendations: [products[0]], citations: [], trace: [searchStep(firstSearchId, 1)] };
  await act(async () => emit({ type: "answer_start", response: answer }));
  const visibleCounts = () => [...document.querySelectorAll(".pg-flow-arms dd")].map((node) => node.textContent);
  expect(visibleCounts()).toEqual(["4", "4", "46"]);
  await act(async () => { emit({ type: "complete", response: { ...answer, recommendations: [products[1]], trace: [...answer.trace, searchStep(secondSearchId, 2)] } }); finish(); });
  expect(visibleCounts()).toEqual(["4", "4", "46"]);
  const selector = screen.getByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" });
  fireEvent.change(selector, { target: { value: secondSearchId } });
  expect(visibleCounts()).toEqual(["0", "0", "50"]);
});

it("keeps the three lessons in view at rest, one per column, before any run", () => {
  vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  const lessons = screen.getAllByLabelText("Keep in mind").map((aside) => aside.textContent ?? "");
  expect(lessons).toHaveLength(4);
  expect(lessons[0]).toContain("A reranker can only reorder what entered this pool");
  expect(lessons[1]).toContain("RRF combines them using 1 / (k + rank)");
  expect(lessons[2]).toContain("Re-rank compares the request");
  expect(lessons[3]).toContain("not citable until the application registers it");
});

it("separates recorded model requests, application steps and missing origins without implying success", async () => {
  const trace: ToolTraceStep[] = [
    { ...searchStep(firstSearchId, 1), tool: "compare_products", origin: "model", outcome: "error" },
    { ...searchStep(firstSearchId, 2), tool: "synthesize_cited_answer", origin: "controller_fallback", outcome: "denied" },
    { ...searchStep(firstSearchId, 3), tool: "get_product_evidence" },
  ];
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
    emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The sources do not support a recommendation.", outcome: "declined", plan: [], recommendations: [], citations: [], trace } });
  });
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  await screen.findByText(/^No recommendation:/);
  fireEvent.click(screen.getByRole("button", { name: "Steps and sources" }));
  const summary = screen.getByLabelText("Who requested the recorded steps");
  expect(summary.textContent).toContain("Requested by the model: 1.");
  expect(summary.textContent).toContain("Started by the application: 1.");
  expect(summary.textContent).toContain("Origin not recorded: 1.");
  fireEvent.click(screen.getByText("Activity log · 3 calls"));
  expect(screen.getByText("Requested by the model", { exact: true })).toBeTruthy();
  expect(screen.getByText("Started by the application", { exact: true })).toBeTruthy();
  expect(screen.getByText("Origin not recorded", { exact: true })).toBeTruthy();
  expect(screen.getByText("error · 10 ms")).toBeTruthy();
  expect(screen.getByText("denied · 10 ms")).toBeTruthy();
});

const measuredArm = (key: ScorecardStageArm["key"], ndcg: number, recall: number, mrr: number): ScorecardStageArm => ({ key, label: key, description: "fixture", recall_at_10: recall, mrr, ndcg_at_10: ndcg, ndcg_at_10_min: 0, ndcg_at_10_max: 1, ndcg_at_10_stdev: 0.2, ndcg_at_10_query_wins: 1 });
const measuredAblation = {
  attributed: true, attribution_note: "", measured_at: "2026-09-10T00:00:00+00:00", spread_note: "", scored_query_count: 20,
  arms: [measuredArm("lexical_only", 0.61, 0.6, 0.65), measuredArm("trigram_only", 0.31, 0.3, 0.35), measuredArm("semantic_only", 0.66, 0.7, 0.71), measuredArm("rrf_fused_no_rerank", 0.83, 0.88, 0.87), measuredArm("rrf_fused_reranked", 0.87, 0.87, 0.93)],
  paired_comparisons: [
    { from_key: "semantic_only", to_key: "rrf_fused_no_rerank", label: "Combining, against meaning match alone", mean_difference: 0.17, difference_stdev: 0.4, wins: 8, losses: 2, ties: 10, separable: false, verdict: "fixture" },
    { from_key: "rrf_fused_no_rerank", to_key: "rrf_fused_reranked", label: "Reranking the combined list", mean_difference: 0.04, difference_stdev: 0.1, wins: 4, losses: 3, ties: 13, separable: false, verdict: "fixture" },
  ],
  candidate_recall_ceiling: { pool_recall_ceiling: 0.95, judged_relevant_never_fetched: 2, description: "fixture" },
  per_query: [],
};
function foundBy(product: ProductSummary, ranks: { fts?: number; trigram?: number; semantic?: number }, final: number): ProductSummary {
  const signal = (value?: number) => ({ rank: value ?? null, raw_score: null, rrf_contribution: null });
  return { ...product, signals: { fts: signal(ranks.fts), trigram: signal(ranks.trigram), semantic: signal(ranks.semantic), rrf_score: 0.02, pre_rerank_rank: final, pre_rerank_score: 0.02, rerank_score: 0.9, rerank_rank: final, final_rank: final, score_semantics: "fixture" } };
}

it("prints what each arm alone scores from the measured artifact and counts this run's one-arm products", async () => {
  vi.spyOn(api, "scorecard").mockResolvedValue({ stage_ablation: measuredAblation } as unknown as RetrievalScorecardResponse);
  const base = fixtureCatalogPage({}, 0, 4).products;
  const products = [foundBy(base[0], { fts: 1 }, 1), foundBy(base[1], { fts: 2, trigram: 1, semantic: 3 }, 2), foundBy(base[2], { semantic: 1 }, 3), foundBy(base[3], { trigram: 2, semantic: 5 }, 4)];
  window.history.replaceState({}, "", `/labs/retrieval?event=${firstSearchId}`);
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(savedSearch(firstSearchId, products));
  render(<PlaygroundPage />);
  expect(screen.queryByRole("table", { name: "Scores for each search method" })).toBeNull();
  fireEvent.click(screen.getByText("Compare search methods"));
  const table = await screen.findByRole("table", { name: "Scores for each search method" });
  expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["Keyword alone", "Close spelling alone", "Meaning alone", "All three combined", "Combined, then reranked"]);
  expect(within(table).getByRole("row", { name: /Keyword alone/ }).textContent).toContain("0.61");
  expect(within(table).getByRole("row", { name: /Combined, then reranked/ }).textContent).toContain("0.93");
  expect(screen.getByText("Combining changes the ordering score (nDCG@10) by +0.17 compared with Meaning alone (inside the spread of these searches); reranking moves it +0.04 (inside the spread of these searches).")).toBeTruthy();
  expect(await screen.findByText("In this run, 2 of the 4 products returned were found by only one search method. Those products depend on the method that found them.")).toBeTruthy();
  expect(screen.getByText(/reranking moved the ordering score by \+0\.04 on average, inside the spread/)).toBeTruthy();
  expect(within(table).getByRole("link", { name: "Open Prove for score definitions and results for each search." }).getAttribute("href")).toBe("/labs/retrieval?view=lab#labs-stage-prove");
});

it("says the measured comparison is waiting when the artifact is not attributed to this build", async () => {
  vi.spyOn(api, "scorecard").mockResolvedValue({ stage_ablation: { ...measuredAblation, attributed: false } } as unknown as RetrievalScorecardResponse);
  render(<PlaygroundPage />);
  expect(await screen.findByText("The measured comparison is waiting for a re-measure on this build.")).toBeTruthy();
  expect(screen.queryByRole("table", { name: "Scores for each search method" })).toBeNull();
});

// The search's first result is not the agent's recommendation. On a declined
// run the plate used to read "Final #1" with nothing saying the agent chose
// nothing, and a replayed search showed no Exact terms at all.
it("says when the agent declined the search's first result, and reads the search's own words", async () => {
  const product = { ...fixtureCatalogPage({}, 0, 1).products[0], signals: undefined } as unknown as ProductSummary;
  const response = savedSearch(firstSearchId, [product]);
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The sources do not support a choice.", outcome: "declined", plan: [], recommendations: [], citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  const lead = await screen.findByRole("region", { name: "First search result" });
  expect(within(lead).getByText("Not recommended: the agent’s sources did not support a choice.")).toBeTruthy();
  expect(within(lead).getByText("Search 1 · First returned result")).toBeTruthy();
  expect(lead.textContent).not.toMatch(/#1|#null/);
  fireEvent.click(screen.getByText("Search record and interpretation"));
  const reads = screen.getByRole("list", { name: "Search 1 reads it as" });
  expect(within(reads).getByText("words not in the saved record")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Alex’s request" })).queryByRole("list", { name: /reads it as/ })).toBeNull();
});

// Shop's Lab 1 callout links here with the lab named. The page used to show a
// plausible other headphone as its first result with no word that the listing
// Alex meant was missing: the trap the lab teaches, sprung by the page itself.
it("names Lab 1's missing target, its cause and the next step on a saved broken run", async () => {
  const mission = mosaicLabManifest.missions.find((item) => item.id === "typo-recovery")!;
  const absent = { rank: null, raw_score: null, rrf_contribution: null };
  const other = {
    ...fixtureCatalogPage({}, 0, 1).products[0],
    ...mission.filters,
    signals: { fts: absent, trigram: absent, semantic: { rank: 8, raw_score: 0.3, rrf_contribution: 0.0147 }, rrf_score: 0.0147, pre_rerank_rank: 8, pre_rerank_score: 0.0147, rerank_score: 0.4, rerank_rank: 1, final_rank: 1, score_semantics: "fixture" },
  } as ProductSummary;
  const broken: SearchResponse = {
    search_event_id: firstSearchId, query: mission.query, normalized_query: mission.query,
    applied_filters: { ...mission.filters }, results: [other],
    diagnostics: { retrieval_profile: {}, candidate_counts: { fused_pool: 50, fts_in_pool: 0, trigram_in_pool: 0, semantic_in_pool: 50 } } as unknown as SearchResponse["diagnostics"],
  };
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(broken);
  window.history.replaceState({}, "", `/labs/retrieval?q=${mission.query}&event=${firstSearchId}&example=typo-recovery`);
  render(<PlaygroundPage />);
  const verdict = await screen.findByRole("region", { name: "Workshop experiment state" });
  expect(within(verdict).getByText(`The ${mission.target_display_name} is missing`)).toBeTruthy();
  expect(verdict.textContent).toContain("returned no candidates");
  expect(verdict.textContent).toContain("Next: in Code Editor, repair the LAB1 block");
  const lead = screen.getByRole("region", { name: "First search result" });
  expect(within(lead).getByText(`Not the listing Alex meant. Lab 1 is looking for the ${mission.target_display_name}.`)).toBeTruthy();
});


it("traces an omitted first result separately from a final choice in another search", async () => {
  const base = fixtureCatalogPage({}, 0, 2).products;
  const omitted = ranked({ ...base[0], title: "BURENMTO Office Chair" }, 46, 1);
  const chosen = ranked({ ...base[1], title: "Novelland Ergonomic Office Chair" }, 10, 1);
  const record: EvidenceRecord = { evidence_id: 7, product_id: chosen.product_id, evidence_type: "product_spec", source_name: "Fixture", source_uri: "https://example.com/spec", revision: "fixture", title: "Adjustments", text: "Adjustable lumbar support", rating: null, is_verified: false, metadata: {} };
  const answer: AgentResponse = {
    agent_run_id: agentId, question: defaultRequest.query, answer: "Novelland is supported by the sources [1].", outcome: "grounded", plan: [], recommendations: [chosen],
    citations: [{ number: 1, evidence_id: record.evidence_id, evidence_type: record.evidence_type, product_id: chosen.product_id, source_uri: record.source_uri, revision: record.revision, title: record.title, quote: record.text }],
    retrieved_evidence: [record, record],
    trace: [searchStep(firstSearchId, 1), searchStep(secondSearchId, 2), { sequence: 3, tool: "compare_products", arguments: { product_ids: [chosen.product_id] }, outcome: "success", detail: "Compared", retrieval_run_id: null, result_count: 1, latency_ms: 10 }],
  };
  vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => savedSearch(id, [id === firstSearchId ? omitted : chosen]));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: answer }));
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Ask about this need" }));
  const summary = await screen.findByRole("region", { name: "Mosaic’s final answer" });
  expect(summary.textContent).toContain("2 searches · 1 product in the answer · 1 cited source");
  expect(within(screen.getByRole("region", { name: "First search result" })).getByText("Not among the agent’s picks.")).toBeTruthy();
  fireEvent.click(within(summary).getByText("Trace all returned products"));
  const rows = within(summary).getAllByRole("row").slice(1);
  expect(within(rows[0]).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Search 1 · #1", "No", "None", "Not included"]);
  expect(within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Search 2 · #1", "Yes", "1 record", "Pick 1 · 1 source"]);
  expect(rows[0].textContent).toContain(`Listing ${omitted.sku}`);
  expect(summary.textContent).toContain("Omission alone does not explain why a product was left out.");
  fireEvent.click(within(summary).getByRole("button", { name: `Trace ${chosen.title}` }));
  expect((screen.getByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" }) as HTMLSelectElement).value).toBe(secondSearchId);
  expect(document.activeElement?.id).toBe(`ranked-product-${chosen.product_id}`);
});
