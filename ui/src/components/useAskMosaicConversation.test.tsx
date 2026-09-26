// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import type { AgentStreamEvent, AgentStreamOptions } from "../api";
import type { AgentConversationContext, SearchFilters } from "../types";
import { useAskMosaicConversation } from "./useAskMosaicConversation";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

/**
 * A stream that never completes on its own; the promise it returns settles
 * only when its caller's `AbortSignal` fires, exactly as `fetch` behaves in
 * `ui/src/api.ts`. Lets a test hold a turn "in flight" and then act on it.
 */
function pendingStream(onEmit?: (event: (event: AgentStreamEvent) => void) => void) {
  return vi.spyOn(api, "agentStream").mockImplementation(
    (
      _question: string,
      _filters: SearchFilters,
      emit: (event: AgentStreamEvent) => void,
      _context?: AgentConversationContext,
      options?: AgentStreamOptions,
    ) => {
      onEmit?.(emit);
      return new Promise((_resolve, reject) => {
        options?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    },
  );
}

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

it("stop ends the in-flight turn as a normal state, not an error, and unblocks a new request", async () => {
  let emitted: ((event: AgentStreamEvent) => void) | undefined;
  const stream = pendingStream((emit) => { emitted = emit; });
  const { result } = renderHook(() => useAskMosaicConversation({}));

  act(() => { void result.current.run("Headphones for clearer calls"); });
  await waitFor(() => expect(result.current.turns).toHaveLength(1));
  expect(result.current.pending).toBe(true);

  // Some progress landed before the reader presses Stop, and that progress
  // must survive the stop: only the loading state ends, not the content.
  act(() => emitted?.({
    type: "answer_delta",
    delta: "The Sonora headphones are quiet enough for",
  }));

  await act(async () => {
    result.current.stop();
    await Promise.resolve();
  });

  expect(result.current.pending).toBe(false);
  const [turn] = result.current.turns;
  expect(turn.loading).toBe(false);
  expect(turn.cancelled).toBe(true);
  expect(turn.error).toBe("");
  expect(turn.streamed).toBe("The Sonora headphones are quiet enough for");

  const optionsPassedToStream = stream.mock.calls[0][4] as AgentStreamOptions | undefined;
  expect(optionsPassedToStream?.signal?.aborted).toBe(true);

  // Stopping must not jam the composer: a fresh request has to go through.
  vi.spyOn(api, "agentStream").mockImplementation(async (question, _filters, emit) => {
    emit({
      type: "complete",
      response: {
        agent_run_id: "run-2", question, answer: "A sourced answer.",
        recommendations: [], citations: [], plan: [], trace: [],
      },
    });
  });
  await act(() => result.current.run("Try again"));
  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[1].cancelled).toBe(false);
  expect(result.current.turns[1].completed).toBe(true);
});

it("stops cleanly under StrictMode's double-invoked mount-time effect", async () => {
  // The hook's own unmount effect follows the project's `requestVersion`
  // idiom for exactly this reason (see `react-strictmode-effect-cleanup-trap`):
  // StrictMode mounts, cleans up, and remounts once more before the test body
  // runs, and a hook that is not ref-guarded would abort or lose a request
  // that started only after that phantom cycle.
  let emitted: ((event: AgentStreamEvent) => void) | undefined;
  pendingStream((emit) => { emitted = emit; });
  const { result } = renderHook(() => useAskMosaicConversation({}), {
    wrapper: StrictMode,
  });

  act(() => { void result.current.run("Headphones for clearer calls"); });
  await waitFor(() => expect(result.current.turns).toHaveLength(1));
  expect(result.current.pending).toBe(true);

  act(() => emitted?.({
    type: "answer_delta",
    delta: "The Sonora headphones are quiet enough for",
  }));

  await act(async () => {
    result.current.stop();
    await Promise.resolve();
  });

  expect(result.current.pending).toBe(false);
  const [turn] = result.current.turns;
  expect(turn.loading).toBe(false);
  expect(turn.cancelled).toBe(true);
  expect(turn.error).toBe("");
  expect(turn.streamed).toBe("The Sonora headphones are quiet enough for");

  vi.spyOn(api, "agentStream").mockImplementation(async (question, _filters, emit) => {
    emit({
      type: "complete",
      response: {
        agent_run_id: "run-2", question, answer: "A sourced answer.",
        recommendations: [], citations: [], plan: [], trace: [],
      },
    });
  });
  await act(() => result.current.run("Try again"));
  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[1].completed).toBe(true);
});

it("unmounting the owner cancels the in-flight request", async () => {
  let capturedSignal: AbortSignal | undefined;
  const stream = pendingStream();
  stream.mockImplementation(
    (_question, _filters, _emit, _context, options?: AgentStreamOptions) => {
      capturedSignal = options?.signal;
      return new Promise((_resolve, reject) => {
        options?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    },
  );
  const { result, unmount } = renderHook(() => useAskMosaicConversation({}));

  act(() => { void result.current.run("Headphones for clearer calls"); });
  await waitFor(() => expect(result.current.pending).toBe(true));

  unmount();
  await Promise.resolve();

  expect(capturedSignal?.aborted).toBe(true);
});
