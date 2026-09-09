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
