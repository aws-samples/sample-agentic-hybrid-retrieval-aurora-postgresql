// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import type { AgentResponse, SearchResponse, ToolTraceStep } from "./types";
import { usePipelineRun } from "./usePipelineRun";

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const agentId = "33333333-3333-4333-8333-333333333333";
const receipt = (id: string): SearchResponse => ({ search_event_id: id, query: `Query ${id}`, normalized_query: "monitor", applied_filters: { domain: "home_office" }, results: [], diagnostics: null });
const step = (id: string, sequence: number): ToolTraceStep => ({ sequence, tool: "search_products", detail: "Search completed", retrieval_run_id: id, result_count: 3, arguments: { query: "monitor" }, outcome: "success", latency_ms: 25 });
const answer = (trace: ToolTraceStep[]): AgentResponse => ({ agent_run_id: agentId, question: "monitor", answer: "A cited recommendation.", plan: [], recommendations: [], citations: [], trace, outcome: "grounded" });

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("one pipeline run", () => {
  it("streams the answer without claiming completion before the terminal event", async () => {
    let emit!: Parameters<typeof api.agentStream>[2];
    let finish!: () => void;
    vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, callback) => {
      emit = callback;
      await new Promise<void>((resolve) => { finish = resolve; });
    });
    const { result } = renderHook(() => usePipelineRun("monitor", null));
    let pending!: Promise<void>;
    act(() => { pending = result.current.play("monitor", {}); });
    const response = answer([]);
    act(() => emit({ type: "answer_start", response: { ...response, answer: "" } }));
    act(() => emit({ type: "answer_delta", delta: "A cited " }));
    expect(result.current.streamed).toBe("A cited ");
    expect(result.current.answer?.agent_run_id).toBe(agentId);
    expect(result.current.completed).toBe(false);
    expect(result.current.running).toBe(true);
    await act(async () => { emit({ type: "complete", response }); finish(); await pending; });
    expect(result.current.streamed).toBe(response.answer);
    expect(result.current.completed).toBe(true);
    expect(result.current.running).toBe(false);
  });

  it("removes interrupted answer text while keeping the available candidate receipt", async () => {
    vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
      emit({ type: "partial", partial: { plan: [], candidates: [], trace: [] } });
      emit({ type: "answer_start", response: { ...answer([]), answer: "" } });
      emit({ type: "answer_delta", delta: "Interrupted answer" });
      throw new ApiError(503, "Stream interrupted", agentId);
    });
    const { result } = renderHook(() => usePipelineRun("monitor", null));
    await act(() => result.current.play("monitor", {}));
    expect(result.current.partial).not.toBeNull();
    expect(result.current.answer).toBeNull();
    expect(result.current.streamed).toBe("");
    expect(result.current.completed).toBe(false);
    expect(result.current.error).toBe("Stream interrupted");
  });

  it("follows the actual agent search IDs once and never starts an independent search", async () => {
    const search = vi.spyOn(api, "search");
    const replay = vi.spyOn(api, "retrievalEventResponse").mockImplementation(async (id) => receipt(id));
    const trace = [step(firstId, 1), step(secondId, 2)];
    const stream = vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
      emit({ type: "partial", partial: { plan: [], candidates: [], trace: [trace[0]] } });
      emit({ type: "partial", partial: { plan: [], candidates: [], trace } });
      emit({ type: "complete", response: answer(trace) });
    });
    const { result } = renderHook(() => usePipelineRun("monitor", null));
    await act(() => result.current.play("monitor", { domain: "home_office" }));
    expect(stream).toHaveBeenCalledTimes(1);
    expect(stream.mock.calls[0].slice(0, 2)).toEqual(["monitor", { domain: "home_office" }]);
    expect(replay.mock.calls).toEqual([[firstId], [secondId]]);
    expect(search).not.toHaveBeenCalled();
    expect(result.current.receipts.map((item) => item.response?.search_event_id)).toEqual([firstId, secondId]);
    expect(result.current.answer?.agent_run_id).toBe(agentId);
    expect(result.current.running).toBe(false);
  });

  it("reads a carried Shop record in StrictMode without running a model", async () => {
    const stream = vi.spyOn(api, "agentStream");
    const search = vi.spyOn(api, "search");
    vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(receipt(firstId));
    const { result } = renderHook(() => usePipelineRun("carried", firstId), { wrapper: StrictMode });
    await waitFor(() => expect(result.current.receipts[0]?.response?.search_event_id).toBe(firstId));
    expect(result.current.reading).toBe(false);
    expect(stream).not.toHaveBeenCalled();
    expect(search).not.toHaveBeenCalled();
    expect(result.current.answer).toBeNull();
  });

  it("retains partial search evidence when synthesis fails closed", async () => {
    vi.spyOn(api, "retrievalEventResponse").mockResolvedValue(receipt(firstId));
    vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
      emit({ type: "partial", partial: { plan: [], candidates: [], trace: [step(firstId, 1)] } });
      throw new ApiError(503, "Evidence not registered", agentId);
    });
    const { result } = renderHook(() => usePipelineRun("monitor", null));
    await act(() => result.current.play("monitor", {}));
    expect(result.current.error).toBe("Evidence not registered");
    expect(result.current.runId).toBe(agentId);
    expect(result.current.answer).toBeNull();
    expect(result.current.receipts[0].response?.search_event_id).toBe(firstId);
    expect(result.current.trace).toHaveLength(1);
  });

  it("keeps a failed receipt distinct from an empty result and preserves the answer", async () => {
    vi.spyOn(api, "retrievalEventResponse").mockRejectedValue(new Error("Record unavailable"));
    vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
      emit({ type: "complete", response: answer([step(firstId, 1)]) });
    });
    const { result } = renderHook(() => usePipelineRun("monitor", null));
    await act(() => result.current.play("monitor", {}));
    expect(result.current.receipts).toEqual([{ id: firstId, error: "Record unavailable" }]);
    expect(result.current.answer?.agent_run_id).toBe(agentId);
  });

  it("discards a late receipt after navigation to a different request", async () => {
    let resolve!: (value: SearchResponse) => void;
    vi.spyOn(api, "retrievalEventResponse").mockReturnValue(new Promise((done) => { resolve = done; }));
    const { result, rerender } = renderHook(({ key, event }) => usePipelineRun(key, event), { initialProps: { key: "old", event: firstId as string | null } });
    rerender({ key: "new", event: null });
    await act(async () => resolve(receipt(firstId)));
    expect(result.current.receipts).toEqual([]);
    expect(result.current.reading).toBe(false);
  });

  it("prevents duplicate Play calls and ignores callbacks from an aborted request", async () => {
    let finish!: () => void;
    let emitOld!: Parameters<typeof api.agentStream>[2];
    const stream = vi.spyOn(api, "agentStream").mockImplementation(async (_question, _filters, emit) => {
      emitOld = emit;
      await new Promise<void>((done) => { finish = done; });
    });
    const replay = vi.spyOn(api, "retrievalEventResponse");
    const { result, rerender } = renderHook(({ key }) => usePipelineRun(key, null), { initialProps: { key: "old" } });
    let pending!: Promise<void>;
    act(() => { pending = result.current.play("monitor", {}); void result.current.play("monitor", {}); });
    expect(stream).toHaveBeenCalledTimes(1);
    rerender({ key: "new" });
    await act(async () => { emitOld({ type: "complete", response: answer([step(firstId, 1)]) }); finish(); await pending; });
    expect(stream.mock.calls[0][4]?.signal?.aborted).toBe(true);
    expect(replay).not.toHaveBeenCalled();
    expect(result.current.answer).toBeNull();
    expect(result.current.running).toBe(false);
  });
});
