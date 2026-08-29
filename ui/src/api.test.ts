import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type AgentStreamEvent } from "./api";
import type { AgentResponse } from "./types";

const response: AgentResponse = {
  agent_run_id: "run-1",
  question: "What should I buy?",
  answer: "Choose the first product.",
  plan: [],
  recommendations: [],
  citations: [],
  trace: [],
};

function sseResponse(frames: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        frames.forEach((frame) => controller.enqueue(encoder.encode(frame)));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

describe("agentStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects a clean EOF that arrives before the complete event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          `event: answer_start\ndata: ${JSON.stringify({ response })}\n\n`,
          `event: answer_delta\ndata: ${JSON.stringify({ delta: "partial" })}\n\n`,
        ]),
      ),
    );

    const events: AgentStreamEvent[] = [];
    const error = await api
      .agentStream("question", {}, (event) => events.push(event))
      .catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 503,
      message: "Agent stream ended before the completion event was received",
    });
    expect(events.map((event) => event.type)).toEqual([
      "answer_start",
      "answer_delta",
    ]);
  });

  it("accepts a stream only after dispatching its complete event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          `event: complete\ndata: ${JSON.stringify({ response })}\n\n`,
        ]),
      ),
    );

    const events: AgentStreamEvent[] = [];
    await api.agentStream("question", {}, (event) => events.push(event));

    expect(events).toEqual([{ type: "complete", response }]);
  });

  it("ignores frames after the terminal complete event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          `event: complete\ndata: ${JSON.stringify({ response })}\n\n`
          + `event: answer_delta\ndata: ${JSON.stringify({ delta: "late" })}\n\n`,
        ]),
      ),
    );

    const events: AgentStreamEvent[] = [];
    await api.agentStream("question", {}, (event) => events.push(event));

    expect(events).toEqual([{ type: "complete", response }]);
  });

  it("passes the backwards-compatible final options signal to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        `event: complete\ndata: ${JSON.stringify({ response })}\n\n`,
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.agentStream(
      "question",
      {},
      () => {},
      undefined,
      { signal: controller.signal },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/agent/answer/stream",
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});
