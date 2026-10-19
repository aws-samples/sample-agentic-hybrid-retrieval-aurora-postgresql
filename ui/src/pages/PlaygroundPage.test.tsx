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

/** An agent answer is read out at the reveal's pace before its picks and sources appear. */
const READ_OUT_MS = 5000;
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
  // The search a participant runs before asking the agent: the API echoes the request it ran.
  vi.spyOn(api, "search").mockImplementation(async (query, filters) => ({ ...savedSearch("44444444-4444-4444-8444-444444444444", []), query, applied_filters: filters as SearchResponse["applied_filters"] }));
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
const DETAILS = { retrieve: "Each search’s top five", rank: "How Aurora combined them", rerank: "Why this position", reason: "Agent steps and sources" } as const;
/** Opens one item of the details row, if it is not open already, and returns its panel. */
function openDetail(label: string) {
  const button = screen.getByRole("button", { name: label });
  if (button.getAttribute("aria-expanded") !== "true") fireEvent.click(button);
  return screen.getByRole("region", { name: label });
}
/** Searches first when no results are shown, then asks the Retrieval agent with the bar's own button. */
async function askAboutThisNeed() {
  const ask = /^(Ask the Retrieval agent|Try again)$/;
  if (!screen.queryByRole("button", { name: ask })) fireEvent.click(screen.getByRole("button", { name: "Run search" }));
  fireEvent.click(await screen.findByRole("button", { name: ask }));
}

it("opens a saved Shop search in the pipeline layout even when the link carries a lab example", async () => {
  const response = savedSearch(firstSearchId, [ranked(fixtureCatalogPage({}, 0, 1).products[0], 2, 1)]);
  window.history.replaceState({}, "", `/labs/retrieval?q=B0C2WWFCQB&event=${firstSearchId}&example=typo-recovery#labs-stage-re-rank`);
  const replay = vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  const search = vi.spyOn(api, "search");
  const stream = vi.spyOn(api, "agentStream");
  render(<PlaygroundPage />);
  expect(screen.queryByText("Guide workbench")).toBeNull();
  await screen.findByRole("heading", { name: response.query });
  expect(screen.getByRole("button", { name: "Why this position" }).getAttribute("aria-expanded")).toBe("true");
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
  openDetail(DETAILS.rerank);
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
  expect(within(screen.getByRole("region", { name: "Product ranking details" })).getAllByRole("listitem")).toHaveLength(4);
  await askAboutThisNeed();
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" });
  expect(stream.mock.calls[0].slice(0, 2)).toEqual([original.query, original.applied_filters]);
  expect(screen.getByRole("heading", { name: original.query })).toBeTruthy();
  expect(screen.getByText(/A new run of the saved Shop search/)).toBeTruthy();
  const back = screen.getByRole("button", { name: "Back to saved Shop results" });
  await waitFor(() => expect((back as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(back);
  await waitFor(() => expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull());
  openDetail(DETAILS.rerank);
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
  await askAboutThisNeed();
  await act(async () => emit({ type: "answer_start", response: answer }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  // The agent's searches wait until its answer has been read out.
  expect(screen.queryByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" })).toBeNull();
  expect(screen.queryByRole("list", { name: "Final ranking preview" })).toBeNull();
  await act(async () => { emit({ type: "complete", response: answer }); finish(); });
  const picks = await screen.findByRole("region", { name: "Mosaic’s picks for Alex" }, { timeout: READ_OUT_MS });
  const selector = await screen.findByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" }) as HTMLSelectElement;
  expect(selector.value).toBe(firstSearchId);
  openDetail(DETAILS.rerank);
  await waitFor(() => expect(productLinks(screen.getByRole("list", { name: "Final ranking preview" }))).toEqual(first.results.map((product) => `/products/${product.product_id}`)));
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
  await askAboutThisNeed();
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
  const play = screen.getByRole("button", { name: "Run search" }) as HTMLButtonElement;
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
  const run = screen.getByRole("region", { name: "This run" });
  await askAboutThisNeed();
  act(() => emit({ type: "partial", partial: { plan: [], candidates: products, trace: [] } }));
  expect(run.querySelectorAll("img")).toHaveLength(0);
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  act(() => emit({ type: "stage", id: "answer", path: "full_retrieval", title: "Answer", detail: "Synthesis" }));
  const running = within(screen.getByRole("list", { name: "The Retrieval agent’s steps" })).getByText("Writing the answer");
  expect(running.closest(".pg-chip")?.getAttribute("data-state")).toBe("running");
  const response: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: `${products[1].title} is the best fit. ${"Full supporting explanation. ".repeat(30)}The final sentence.`, plan: [], recommendations: [products[1], products[0]], citations: [], trace: [] };
  act(() => emit({ type: "answer_start", response: { ...response, answer: "" } }));
  act(() => emit({ type: "answer_delta", delta: `${products[1].title} is the best fit.` }));
  await waitFor(() => expect(run.querySelector(".inspector-answer")?.textContent).toContain(`${products[1].title} is the best fit.`));
  expect(run.querySelectorAll(".inspector-answer .reveal-chunk").length).toBeGreaterThan(1);
  expect(run.querySelectorAll("img")).toHaveLength(0);
  expect(container.querySelector(".inspector-answer")?.getAttribute("aria-busy")).toBe("true");
  await act(async () => { emit({ type: "complete", response }); finish(); });
  // The picks and sources wait until the prose has been read out, so they never push it down.
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  const picks = await screen.findByRole("region", { name: "Mosaic’s picks for Alex" }, { timeout: READ_OUT_MS });
  expect(productLinks(picks)).toEqual([products[1], products[0]].map((product) => `/products/${product.product_id}`));
  const prose = run.querySelector(".inspector-answer")!;
  expect(prose.textContent).toContain("The final sentence.");
  expect(prose.closest("details")).toBeNull();
  expect(prose.compareDocumentPosition(picks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(prose.getAttribute("aria-busy")).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "More screen space" }));
  expect(screen.queryByRole("region", { name: "Mosaic’s picks for Alex" })).toBeNull();
  expect(container.querySelector(".inspector-answer")).toBeNull();
});

it("shows one running chip while the agent works, and none once it finishes", async () => {
  let emit!: Parameters<typeof api.agentStream>[2];
  let finish!: () => void;
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
    emit = callback;
    await new Promise<void>((resolve) => { finish = resolve; });
  });
  render(<PlaygroundPage />);
  await askAboutThisNeed();
  const chips = () => [...screen.getByRole("list", { name: "The Retrieval agent’s steps" }).querySelectorAll(".pg-chip")].map((chip) => chip.getAttribute("data-state"));
  for (const id of ["rank", "answer", "retrieve"] as const) {
    act(() => emit({ type: "stage", id, path: "full_retrieval", title: id, detail: id }));
    expect(chips()).toEqual(["running"]);
  }
  await act(async () => {
    emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "Finished.", plan: [], recommendations: [], citations: [], trace: [] } });
    finish();
  });
  expect(document.querySelector('.pg-chip[data-state="running"]')).toBeNull();
});

it.each(["retrieve", "rank", "answer"] as const)("stops showing progress after a failure at %s and supports retry", async (id) => {
  const stream = vi.spyOn(api, "agentStream").mockImplementationOnce(async (_question, _filters, emit) => {
    emit({ type: "stage", id, path: "full_retrieval", title: id, detail: id });
    throw new Error("Catalog connection unavailable.");
  });
  render(<PlaygroundPage />);
  await askAboutThisNeed();
  await screen.findByRole("alert");
  expect(document.querySelector('.pg-chip[data-state="running"]')).toBeNull();
  expect(screen.getByText("No ranking is available from this run.")).toBeTruthy();
  stream.mockImplementationOnce(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "Recovered.", plan: [], recommendations: [], citations: [], trace: [] } }));
  await askAboutThisNeed();
  await screen.findByText("Recovered.");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("opens one detail at a time, and a pick's search link opens Why this position", async () => {
  const products = fixtureCatalogPage({}, 0, 2).products.map((product, index) => ranked(product, index + 4, index + 1));
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(savedSearch(firstSearchId, products));
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The recorded answer.", plan: [], recommendations: products, citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  await askAboutThisNeed();
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" }, { timeout: READ_OUT_MS });
  for (const label of Object.values(DETAILS)) {
    openDetail(label);
    expect(screen.getAllByRole("button", { expanded: true }).map((button) => button.textContent)).toEqual([label]);
  }
  fireEvent.click(screen.getByRole("button", { name: DETAILS.reason }));
  expect(screen.queryAllByRole("button", { expanded: true })).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: `${products[0].title}: show Search 1, rank 1` }));
  expect(screen.getByRole("button", { name: DETAILS.rerank }).getAttribute("aria-expanded")).toBe("true");
  expect(document.activeElement?.id).toBe(`ranked-product-${products[0].product_id}`);
});

it("opens on Clearer calls, offers one Play action, and keeps guide links working", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  expect(screen.getByRole("heading", { name: callsRequest.query })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Focus at home" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Ask the Retrieval agent" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Run search" }));
  expect(await screen.findAllByRole("button", { name: "Ask the Retrieval agent" })).toHaveLength(1);
  expect(stream).not.toHaveBeenCalled();
  await askAboutThisNeed();
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
  await askAboutThisNeed();
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" }, { timeout: READ_OUT_MS });
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  openDetail(DETAILS.rerank);
  expect(await screen.findByRole("region", { name: "Product ranking details" })).toBeTruthy();
  expect(screen.getAllByLabelText("#27 before rerank, #1 in the final order")).toHaveLength(1);
  expect(screen.getByText("The recorded answer.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "More screen space" }));
  expect(screen.queryByLabelText("#27 before rerank, #1 in the final order")).toBeNull();
  expect(screen.queryByRole("region", { name: "Product ranking details" })).toBeNull();
  expect(screen.queryByText("The recorded answer.")).toBeNull();
});

it("runs the canonical multi-part request from the new Pipeline choice", async () => {
  const stream = vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  fireEvent.click(screen.getByRole("button", { name: "Complete my setup" }));
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
  await askAboutThisNeed();
  const answer: AgentResponse = { agent_run_id: agentId, question: defaultRequest.query, answer: "Completed.", plan: [], recommendations: [products[0]], citations: [], trace: [searchStep(firstSearchId, 1)] };
  await act(async () => emit({ type: "answer_start", response: answer }));
  // Each search column's header says how many of its matches reached the pool.
  const visibleCounts = () => [...document.querySelectorAll(".method-meta")].map((node) => /^\d+/.exec(node.textContent ?? "")?.[0]);
  expect(visibleCounts()).toEqual([]);
  await act(async () => { emit({ type: "complete", response: { ...answer, recommendations: [products[1]], trace: [...answer.trace, searchStep(secondSearchId, 2)] } }); finish(); });
  await screen.findByRole("region", { name: "Mosaic’s picks for Alex" }, { timeout: READ_OUT_MS });
  openDetail(DETAILS.retrieve);
  await waitFor(() => expect(visibleCounts()).toEqual(["4", "4", "46"]));
  const selector = screen.getByRole("combobox", { name: "Search shown in Retrieve, Rank and Re-rank" });
  fireEvent.change(selector, { target: { value: secondSearchId } });
  openDetail(DETAILS.retrieve);
  expect(visibleCounts()).toEqual(["0", "0", "50"]);
});

it("keeps one sentence per stage in view and opens each stage's details with its lesson", () => {
  vi.spyOn(api, "agentStream").mockResolvedValue(undefined);
  render(<PlaygroundPage />);
  expect(screen.queryAllByLabelText("Keep in mind")).toHaveLength(0);
  const lessons: [string, string][] = [
    [DETAILS.retrieve, "A reranker can only reorder what entered this pool."],
    [DETAILS.rank, "A right winner can hide broken fusion"],
    [DETAILS.rerank, "cannot recover a product Rank excluded"],
    [DETAILS.reason, "missing support stays an open question"],
  ];
  for (const [details, lesson] of lessons) {
    expect(document.body.textContent).not.toContain(lesson);
    expect(openDetail(details).textContent).toContain(lesson);
    fireEvent.click(screen.getByRole("button", { name: details }));
  }
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
  await askAboutThisNeed();
  await screen.findByText(/^No recommendation:/);
  openDetail(DETAILS.reason);
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
    { from_key: "semantic_only", to_key: "rrf_fused_no_rerank", label: "Combining, against semantic search alone", mean_difference: 0.17, difference_stdev: 0.4, wins: 8, losses: 2, ties: 10, separable: false, verdict: "fixture" },
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
  openDetail(DETAILS.retrieve);
  await waitFor(() => expect(document.querySelectorAll(".method-column")).toHaveLength(3));
  openDetail(DETAILS.retrieve);
  fireEvent.click(screen.getByText("Compare search methods"));
  const table = await screen.findByRole("table", { name: "Scores for each search method" });
  expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["Full-text search alone", "Fuzzy matching alone", "Semantic search alone", "All three combined", "Combined, then reranked"]);
  expect(within(table).getByRole("row", { name: /Full-text search alone/ }).textContent).toContain("0.61");
  expect(within(table).getByRole("row", { name: /Combined, then reranked/ }).textContent).toContain("0.93");
  expect(screen.getByText("Combining changes the ordering score (nDCG@10) by +0.17 compared with Semantic search alone (inside the spread of these searches); reranking moves it +0.04 (inside the spread of these searches).")).toBeTruthy();
  expect(within(table).getByRole("link", { name: "Open Prove for score definitions and results for each search." }).getAttribute("href")).toBe("/labs/retrieval?view=lab#labs-stage-prove");
  openDetail(DETAILS.rerank);
  expect(screen.getByText(/reranking moved the ordering score by \+0\.04 on average, inside the spread/)).toBeTruthy();
});

it("says the measured comparison is waiting when the artifact is not attributed to this build", async () => {
  vi.spyOn(api, "scorecard").mockResolvedValue({ stage_ablation: { ...measuredAblation, attributed: false } } as unknown as RetrievalScorecardResponse);
  render(<PlaygroundPage />);
  openDetail(DETAILS.retrieve);
  expect(await screen.findByText("The measured comparison is waiting for a re-measure on this build.")).toBeTruthy();
  expect(screen.queryByRole("table", { name: "Scores for each search method" })).toBeNull();
});

// The search's first result is not the agent's recommendation. On a declined
// run the plate used to read "Final #1" with nothing saying the agent chose
// nothing, and a replayed search showed no Full-text search at all.
it("says when the agent declined the search's first result, and reads the search's own words", async () => {
  const product = { ...fixtureCatalogPage({}, 0, 1).products[0], signals: undefined } as unknown as ProductSummary;
  const response = savedSearch(firstSearchId, [product]);
  vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(response);
  vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => emit({ type: "complete", response: { agent_run_id: agentId, question: defaultRequest.query, answer: "The sources do not support a choice.", outcome: "declined", plan: [], recommendations: [], citations: [], trace: [searchStep(firstSearchId, 1)] } }));
  render(<PlaygroundPage />);
  await askAboutThisNeed();
  expect(await screen.findByText("No recommendation: the available sources do not support a choice.")).toBeTruthy();
  // Each search column says how it read the request; a replayed record keeps no words.
  await screen.findByText("No recommendation: the available sources do not support a choice.");
  await waitFor(() => expect(screen.getByRole("button", { name: DETAILS.retrieve })).toBeTruthy());
  await waitFor(() => { openDetail(DETAILS.retrieve); expect(document.querySelectorAll(".method-column")).toHaveLength(3); }, { timeout: READ_OUT_MS });
  const reads = within(openDetail(DETAILS.retrieve)).getByLabelText("Full-text search reads the request as");
  expect(reads.textContent).toContain("words not in the saved record");
  expect(screen.getByRole("list", { name: "The Retrieval agent’s steps" }).textContent).toContain(firstSearchId.slice(0, 8));
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
  expect(within(openDetail(DETAILS.retrieve)).getByText(`The ${mission.target_display_name} is not among the products this search returned.`)).toBeTruthy();
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
  await askAboutThisNeed();
  const summary = await screen.findByRole("region", { name: "Where the picks came from" });
  expect(summary.textContent).toContain("2 searches · 1 product in the answer · 1 cited source");
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
