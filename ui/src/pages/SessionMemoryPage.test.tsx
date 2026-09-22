// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../api";
import type { SessionMemoryResponse, ShopperSession } from "../types";
import { SessionMemoryPage } from "./SessionMemoryPage";
import missionManifest from "../../../data/evals/mosaic_labs_missions.json";

const response: SessionMemoryResponse = {
  memory_status: "connected", actor_id: "alex-browser", active_session_id: null, sessions: [],
  configuration: { memory_id: "mosaic-memory", status: "ACTIVE", event_expiry_days: 30,
    strategies: ["SEMANTIC", "USER_PREFERENCE", "SUMMARIZATION", "EPISODIC"].map((type) => ({ id: type, name: type, type, status: "ACTIVE", namespaces: ["/mosaic/{actorId}/"], reflection_namespaces: [] })) },
};
beforeEach(() => {
  vi.spyOn(api, "sessionMemory").mockResolvedValue(structuredClone(response));
  vi.spyOn(api, "memoryEvents").mockResolvedValue({ events: [], has_more: false });
  vi.spyOn(api, "memoryRecords").mockResolvedValue({ records: [], has_more: false, namespaces: [] });
  vi.spyOn(api, "newSession").mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("loads the optional lab requests without sending them or changing the memory opt-in", async () => {
  const stream = vi.spyOn(api, "agentStream");
  const recall = vi.spyOn(api, "recallMemory");
  render(<SessionMemoryPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Change Alex’s request" }));
  expect(screen.getByLabelText("Ask about Alex’s workspace")).toHaveProperty("value", missionManifest.optional_labs.memory.changed_request);
  expect(screen.getByLabelText("Use AgentCore Memory for this request")).toHaveProperty("checked", true);
  fireEvent.click(screen.getByRole("button", { name: "Original question" }));
  expect(screen.getByLabelText("Ask about Alex’s workspace")).toHaveProperty("value", missionManifest.optional_labs.memory.request);
  expect(stream).not.toHaveBeenCalled();
  expect(recall).not.toHaveBeenCalled();
});

it("stops the loading indicator after an initial failure and retries the connection", async () => {
  vi.mocked(api.sessionMemory).mockRejectedValueOnce(new Error("Catalog connection unavailable."));
  render(<SessionMemoryPage />);
  await screen.findByRole("alert");
  expect(screen.queryByText("Loading conversations and memory settings…")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("heading", { name: "What AgentCore remembers" });
  expect(api.sessionMemory).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each([
  ['{"fact":"Alex shares an office."}', "Alex shares an office."],
  ['{"summary":"Alex compared two keyboards."}', "Alex compared two keyboards."],
  ['{"turns":[null,{"situation":"Alex needs quieter typing.","thought":"Internal processing details"}]}', "Alex needs quieter typing."],
  ['{"unknown_format":{"detail":"Original content"}}', "This memory contains structured details. Open Record details to inspect what AgentCore saved."],
  ["null", "This memory contains structured details. Open Record details to inspect what AgentCore saved."],
])("previews memory content and preserves the complete original record: %s", async (text, preview) => {
  vi.mocked(api.memoryRecords).mockResolvedValue({ records: [{ id: "record-1", strategy_id: "SEMANTIC", text, namespaces: ["/mosaic/alex-browser/"], created_at: "2026-09-17T12:00:00Z", score: null }], has_more: false, namespaces: [] });
  render(<SessionMemoryPage />);
  const summary = await screen.findByText(preview, { selector: "p" });
  const details = summary.closest("article")!.querySelector("details")!;
  expect(details.open).toBe(false);
  expect(details.querySelector("pre")!.textContent).toBe(text);
});

it("teaches the four strategies and never presents a budget form", async () => {
  render(<SessionMemoryPage />);
  await screen.findByRole("heading", { name: "What AgentCore remembers" });
  expect(screen.queryByLabelText(/budget/i)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Past outcomes.*What worked/ }));
  await screen.findByText(/AgentCore saves an outcome after it detects/);
  await waitFor(() => expect(api.memoryRecords).toHaveBeenCalledWith("EPISODIC", undefined));
  expect(screen.getByText("No records returned yet.")).toBeTruthy();
});
it("stores the actual event then reads the selected session without claiming extraction completed", async () => {
  vi.spyOn(api, "addMemoryEvent").mockResolvedValue({ session_id: "session-1", event_id: "event-1" });
  render(<SessionMemoryPage />);
  const input = await screen.findByLabelText("Alex says");
  fireEvent.change(input, { target: { value: "I share an office and prefer quiet typing." } });
  fireEvent.click(screen.getByRole("button", { name: "Save message" }));
  await waitFor(() => expect(api.addMemoryEvent).toHaveBeenCalledWith("I share an office and prefer quiet typing.", undefined));
  await screen.findByText(/Message saved in AgentCore. It processes useful details in the background/);
  await waitFor(() => expect(api.memoryEvents).toHaveBeenCalledWith("session-1"));
});
it("new sessions keep the actor and can recall real records independently of events", async () => {
  const recall = vi.spyOn(api, "recallMemory").mockResolvedValue({ records: [{ id: "record-1", strategy_id: "SEMANTIC", text: "Alex shares an office", namespaces: ["/mosaic/alex/"], created_at: "2026-09-09T10:00:00Z", score: .8 }] });
  render(<SessionMemoryPage />);
  fireEvent.click(await screen.findByRole("button", { name: "New session" }));
  await screen.findByText(/New session. Alex keeps the same user ID/);
  fireEvent.click(screen.getByRole("button", { name: "Find relevant memories" }));
  await screen.findByText("Alex shares an office", { selector: "p" });
  expect(recall).toHaveBeenCalledWith("Which monitor would suit the way I work at home?");
});
it("starts with a fresh Alex and clears recalled memories without running the agent", async () => {
  vi.spyOn(api, "recallMemory").mockResolvedValue({ records: [{ id: "old-fact", strategy_id: "SEMANTIC", text: "Earlier Alex’s preference", namespaces: ["/mosaic/alex-browser/"], created_at: "2026-09-09T17:45:00Z", score: null }] });
  const stream = vi.spyOn(api, "agentStream");
  const reset = vi.spyOn(api, "resetAlex").mockImplementation(async () => {
    vi.mocked(api.sessionMemory).mockResolvedValue({ ...response, actor_id: "fresh-alex" });
  });
  render(<SessionMemoryPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Find relevant memories" }));
  await screen.findByText("Earlier Alex’s preference", { selector: "p" });
  fireEvent.click(screen.getByRole("button", { name: "Start fresh" }));
  await screen.findByText(/A fresh start for Alex/);
  expect(screen.getByText("fresh-alex")).toBeTruthy();
  expect(screen.queryByText("Earlier Alex’s preference")).toBeNull();
  expect(screen.getByLabelText("Session")).toHaveProperty("value", "");
  expect(screen.getByText("Your answer will appear here after you ask Mosaic.")).toBeTruthy();
  expect(reset).toHaveBeenCalledOnce();
  expect(api.newSession).not.toHaveBeenCalled();
  expect(stream).not.toHaveBeenCalled();
});
it("shows a failed record read as an error rather than an empty successful extraction", async () => {
  vi.mocked(api.memoryRecords).mockRejectedValue(new Error("AgentCore access denied"));
  render(<SessionMemoryPage />);
  await screen.findByRole("alert");
  expect(screen.getByText("AgentCore access denied")).toBeTruthy();
  expect(screen.queryByText("No records returned yet.")).toBeNull();
});
it("memory opt-out reaches the agent while visible progress remains", async () => {
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (_q, _f, onEvent) => {
    onEvent({ type: "stage", id: "retrieve", path: "full_retrieval", title: "Finding products", detail: "Reading the catalog" });
    throw new Error("Paused test request");
  });
  render(<SessionMemoryPage />);
  fireEvent.click(await screen.findByLabelText("Use AgentCore Memory for this request"));
  fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
  await screen.findByText("Paused test request");
  expect(stream).toHaveBeenCalledWith(expect.any(String), {}, expect.any(Function), undefined, expect.objectContaining({ useMemory: false }));
});

it("keeps saved answers collapsed and shows only a newly requested answer inline", async () => {
  const oldTurn: ShopperSession["turns"][number] = {
    run_id: "old-run", question: "An earlier question", answer: "Previously saved answer.",
    created_at: "2026-09-09T10:00:00Z", products: [], search_ids: [], citations: [], memory: {},
  };
  const session: ShopperSession = {
    agent_session_id: "session-1", started_at: oldTurn.created_at, ended_at: null,
    label: "Alex’s workspace", turns: [oldTurn],
  };
  vi.mocked(api.sessionMemory).mockResolvedValue({ ...response, active_session_id: session.agent_session_id, sessions: [session] });
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (question, _filters, onEvent) => {
    const turn = { ...oldTurn, run_id: "new-run", question, answer: "Answer from this request." };
    vi.mocked(api.sessionMemory).mockResolvedValue({ ...response, active_session_id: session.agent_session_id, sessions: [{ ...session, turns: [oldTurn, turn] }] });
    onEvent({ type: "complete", response: { agent_run_id: turn.run_id, question, answer: turn.answer, recommendations: [], citations: [], plan: [], trace: [] } });
  });
  const view = render(<SessionMemoryPage />);
  const previousAnswer = await screen.findByText("Previously saved answer.");
  expect(previousAnswer.closest("details")?.open).toBe(false);
  expect(view.container.querySelector(".memory-current-answer")).toBeNull();
  expect(stream).not.toHaveBeenCalled();
  expect(screen.getByText("Your answer will appear here after you ask Mosaic.")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Ask Mosaic" }));
  await waitFor(() => expect(view.container.querySelector(".memory-current-answer")?.textContent).toContain("Answer from this request."));
  expect(previousAnswer.closest("details")?.open).toBe(false);
  expect(screen.getAllByText("Answer from this request.")).toHaveLength(1);

  view.unmount();
  const reopened = render(<SessionMemoryPage />);
  const savedNewAnswer = await screen.findByText("Answer from this request.");
  expect(savedNewAnswer.closest("details")?.open).toBe(false);
  expect(reopened.container.querySelector(".memory-current-answer")).toBeNull();
  expect(stream).toHaveBeenCalledTimes(1);
});

it("says when a session's runs kept memory off, and names each record's scope", async () => {
  const session: ShopperSession = {
    agent_session_id: "session-off", started_at: "2026-09-09T17:44:11Z", ended_at: null, label: null,
    turns: [{ run_id: "run-1", question: "I take video calls from home", answer: "Answer.", created_at: "2026-09-09T17:44:40Z", products: [], search_ids: [], citations: [], memory: { status: "off", enabled: false, records: [], event_ids_read: [] } }],
  };
  vi.mocked(api.sessionMemory).mockResolvedValue({ ...structuredClone(response), sessions: [session], active_session_id: "session-off" });
  vi.mocked(api.memoryRecords).mockResolvedValue({ has_more: false, namespaces: [], records: [
    { id: "fact-1", strategy_id: "SEMANTIC", text: "Alex shares an office.", namespaces: ["/mosaic/alex-browser/strategies/SEMANTIC/"], created_at: "2026-09-09T17:45:00Z", score: null },
    { id: "summary-1", strategy_id: "SEMANTIC", text: "Alex asked about headphones.", namespaces: ["/mosaic/alex-browser/strategies/SEMANTIC/sessions/session-off/"], created_at: "2026-09-09T17:46:00Z", score: null },
  ] });
  render(<SessionMemoryPage />);
  await screen.findByText(/Memory was off for these requests, so their messages were not saved in AgentCore/);
  expect(screen.queryByText("No saved messages were returned for this session.")).toBeNull();
  await screen.findByText("Alex shares an office.", { selector: "p" });
  expect(screen.getByText("Kept for Alex across sessions")).toBeTruthy();
  expect(screen.getByText("From this session")).toBeTruthy();
});
