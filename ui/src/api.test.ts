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

/** Answers the identity request, then serves `stream` for the ask itself. */
function streamFetch(stream: Response) {
  return vi.fn((url: string) => Promise.resolve(
    url === "/api/session-memory/identity" ? new Response(JSON.stringify({ ready: true })) : stream,
  ));
}

describe("catalog filters", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("preserves JSON attributes and repeated brands when browsing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    const attributes = { active_noise_cancellation: true, connectivity: ["Bluetooth"] };

    await api.catalog({ attributes, brands: ["Sonora", "AuriLogic"] }, 12, 12, "price_asc");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = new URL(fetchMock.mock.calls[0][0], "https://mosaic.example");
    expect(JSON.parse(url.searchParams.get("attributes")!)).toEqual(attributes);
    expect(url.searchParams.getAll("brands")).toEqual(["Sonora", "AuriLogic"]);
    expect(url.searchParams.get("offset")).toBe("12");
    expect(url.searchParams.get("sort")).toBe("price_asc");
  });
});

describe("agentStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the persisted failed run id on a terminal error", async () => {
    vi.stubGlobal("fetch", streamFetch(sseResponse([
      'event: error\ndata: {"detail":"Grounding refused","agent_run_id":"failed-run","code":"grounding_contract"}\n\n',
    ])));
    await expect(api.agentStream("question", {}, () => {})).rejects.toMatchObject({
      message: "Grounding refused", agentRunId: "failed-run", status: 503,
    });
  });

  it("rejects a clean EOF that arrives before the complete event", async () => {
    vi.stubGlobal(
      "fetch",
      streamFetch(
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
      streamFetch(
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
      streamFetch(
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

  // A follow-up carries the first turn's session, and the server continues a
  // session only for the browser that owns it. With memory off the first turn
  // used to run with no owner, so every follow-up in a new browser was a 404.
  it("establishes the browser identity before every ask, memory on or off", async () => {
    const fetchMock = vi.fn((url: string) => streamFetch(
      sseResponse([`event: complete\ndata: ${JSON.stringify({ response })}\n\n`]),
    )(url));
    vi.stubGlobal("fetch", fetchMock);

    await api.agentStream("question", {}, () => {});
    await api.agentStream("follow-up", {}, () => {}, undefined, { sessionId: "session-1" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/session-memory/identity",
      "/api/agent/answer/stream",
      "/api/session-memory/identity",
      "/api/agent/answer/stream",
    ]);
  });

  it("passes the backwards-compatible final options signal to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = streamFetch(
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
