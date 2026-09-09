// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../api";
import type { SessionMemoryResponse, ShopperSession } from "../types";
import { SessionMemoryPage } from "./SessionMemoryPage";

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

it("teaches the four strategies and never presents a budget form", async () => {
  render(<SessionMemoryPage />);
  await screen.findByRole("heading", { name: "What the strategies keep" });
  expect(screen.queryByLabelText(/budget/i)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Episodes.*Episodic/ }));
  await screen.findByText(/An episode appears after AgentCore detects/);
  await waitFor(() => expect(api.memoryRecords).toHaveBeenCalledWith("EPISODIC", undefined));
  expect(screen.getByText("No records returned yet.")).toBeTruthy();
});
it("stores the actual event then reads the selected session without claiming extraction completed", async () => {
  vi.spyOn(api, "addMemoryEvent").mockResolvedValue({ session_id: "session-1", event_id: "event-1" });
  render(<SessionMemoryPage />);
  const input = await screen.findByLabelText("Alex says");
  fireEvent.change(input, { target: { value: "I share an office and prefer quiet typing." } });
  fireEvent.click(screen.getByRole("button", { name: "Add conversation event" }));
  await waitFor(() => expect(api.addMemoryEvent).toHaveBeenCalledWith("I share an office and prefer quiet typing.", undefined));
  await screen.findByText(/Event stored in AgentCore. Memory extraction runs separately/);
  await waitFor(() => expect(api.memoryEvents).toHaveBeenCalledWith("session-1"));
});
it("new sessions keep the actor and can recall real records independently of events", async () => {
  const recall = vi.spyOn(api, "recallMemory").mockResolvedValue({ records: [{ id: "record-1", strategy_id: "SEMANTIC", text: "Alex shares an office", namespaces: ["/mosaic/alex/"], created_at: "2026-09-09T10:00:00Z", score: .8 }] });
  render(<SessionMemoryPage />);
  fireEvent.click(await screen.findByRole("button", { name: "New session" }));
  await screen.findByText(/New session. Alex keeps the same actor ID/);
  fireEvent.click(screen.getByRole("button", { name: "Recall memories" }));
  await screen.findByText("Alex shares an office", { selector: "p" });
  expect(recall).toHaveBeenCalledWith("Which headphones would suit the way I work at home?");
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
