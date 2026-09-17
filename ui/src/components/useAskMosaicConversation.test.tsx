// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { useAskMosaicConversation } from "./useAskMosaicConversation";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("starts fresh retrieval after a decline without losing the visible conversation", async () => {
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (question, _filters, emit) => {
    emit({ type: "complete", response: {
      agent_run_id: "declined-run", question, answer: "The catalog does not carry that model.",
      outcome: "declined", recommendations: [], citations: [], plan: [], trace: [],
    } });
  });
  const { result } = renderHook(() => useAskMosaicConversation({}));
  await act(() => result.current.run("An unavailable model"));
  await act(() => result.current.run("Show headphones for clearer calls"));
  expect(stream).toHaveBeenCalledTimes(2);
  expect(stream.mock.calls[1][3]).toBeUndefined();
  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[1].executionPath).toBe("full_retrieval");
});

it("honors memory opt-in, keeps a session for follow-ups, and starts a new session after clear", async () => {
  const stream = vi.spyOn(api, "agentStream").mockImplementation(async (question, _filters, emit) => {
    emit({ type: "complete", response: {
      agent_run_id: "run", session_id: "owned-session", question, answer: "A sourced answer.",
      recommendations: [], citations: [], plan: [], trace: [],
    } });
  });
  const { result, rerender } = renderHook(({ enabled }) => useAskMosaicConversation({}, enabled), {
    initialProps: { enabled: false },
  });
  await act(() => result.current.run("Headphones for clearer calls"));
  expect(stream.mock.calls[0][4]).toMatchObject({ useMemory: false, sessionId: undefined });
  rerender({ enabled: true });
  await act(() => result.current.run("What do their reviews say?"));
  expect(stream.mock.calls[1][4]).toMatchObject({ useMemory: true, sessionId: "owned-session" });
  act(() => result.current.clear());
  await act(() => result.current.run("Headphones for my workspace"));
  expect(stream.mock.calls[2][4]).toMatchObject({ useMemory: true, sessionId: undefined });
  rerender({ enabled: false });
  await act(() => result.current.run("Explain their specifications"));
  expect(stream.mock.calls[3][4]).toMatchObject({ useMemory: false, sessionId: "owned-session" });
});
