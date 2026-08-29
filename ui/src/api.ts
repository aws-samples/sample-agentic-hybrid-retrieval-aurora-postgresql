import type {
  AgentConversationContext,
  AgentPartial,
  AgentResponse,
  BenchmarkProjection,
  CatalogPage,
  CatalogSuggestionsResponse,
  CatalogSummary,
  EvidenceRecord,
  HnswMeasured,
  HnswNeighborhood,
  HnswProbe,
  HnswProbeInput,
  HnswSubstrate,
  ProductDetail,
  ReadinessResponse,
  RetrievalExample,
  RetrievalPlanResponse,
  RetrievalRunResponse,
  RetrievalScorecardResponse,
  ReviewHighlight,
  SearchFilters,
  SearchResponse,
  ToolContract,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type AgentStreamEvent =
  | {
    type: "stage";
    id: "understand" | "retrieve" | "rank" | "answer";
    path: "focused_follow_up" | "full_retrieval";
    title: string;
    detail: string;
  }
  | { type: "partial"; partial: AgentPartial }
  | { type: "answer_start"; response: AgentResponse }
  | { type: "answer_delta"; delta: string }
  | { type: "complete"; response: AgentResponse };

export type AgentStreamOptions = {
  signal?: AbortSignal;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the bounded status message.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

async function streamResponseError(response: Response): Promise<ApiError> {
  let message = `Request failed with HTTP ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) message = body.detail;
  } catch {
    // Preserve the concise HTTP error when the response body is not JSON.
  }
  return new ApiError(response.status, message);
}

function parseSseFrame(frame: string): { event: string; data: string } | null {
  const lines = frame.split("\n");
  const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines.find((line) => line.startsWith("data: "))?.slice(6);
  return event && data ? { event, data } : null;
}

export const api = {
  summary: () => request<CatalogSummary>("/api/catalog/summary"),

  suggestions: (query: string, signal?: AbortSignal) =>
    request<CatalogSuggestionsResponse>(
      `/api/catalog/suggestions?q=${encodeURIComponent(query)}`,
      { signal },
    ),

  catalog: (filters: SearchFilters, offset = 0, limit = 12, sort = "featured") => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
      sort,
    });
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && key !== "attributes") {
        params.set(key, String(value));
      }
    });
    return request<CatalogPage>(`/api/catalog/products?${params}`);
  },

  product: (productId: number) =>
    request<ProductDetail>(`/api/products/${productId}`),

  reviewHighlights: async () => {
    const body = await request<{ highlights: ReviewHighlight[] }>(
      "/api/catalog/reviews/highlights",
    );
    return body.highlights;
  },

  search: (
    query: string,
    filters: SearchFilters,
    options: { limit?: number; rerank?: boolean; signal?: AbortSignal } = {},
  ) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      signal: options.signal,
      body: JSON.stringify({
        query,
        filters,
        limit: options.limit ?? 12,
        include_diagnostics: true,
        rerank: options.rerank ?? true,
      }),
    }),

  agent: (
    question: string,
    filters: SearchFilters,
    context?: AgentConversationContext,
  ) =>
    request<AgentResponse>("/api/agent/answer", {
      method: "POST",
      body: JSON.stringify({
        question,
        filters,
        result_limit: 6,
        context,
      }),
    }),

  agentStream: async (
    question: string,
    filters: SearchFilters,
    onEvent: (event: AgentStreamEvent) => void,
    context?: AgentConversationContext,
    options: AgentStreamOptions = {},
  ) => {
    const response = await fetch("/api/agent/answer/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: options.signal,
      body: JSON.stringify({
        question,
        filters,
        result_limit: 6,
        context,
      }),
    });
    if (!response.ok) throw await streamResponseError(response);
    if (!response.body) throw new ApiError(503, "Agent stream was unavailable");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const parsed = parseSseFrame(frame);
          if (parsed) {
            const payload = JSON.parse(parsed.data) as Record<string, unknown>;
            if (parsed.event === "error") {
              throw new ApiError(503, String(payload.detail ?? "Agent stream failed"));
            }
            if (parsed.event === "stage") {
              onEvent({ type: "stage", ...payload } as AgentStreamEvent);
            } else if (parsed.event === "partial") {
              onEvent({
                type: "partial",
                partial: payload.partial as AgentPartial,
              });
            } else if (parsed.event === "answer_start") {
              onEvent({
                type: "answer_start",
                response: payload.response as AgentResponse,
              });
            } else if (parsed.event === "answer_delta") {
              onEvent({ type: "answer_delta", delta: String(payload.delta ?? "") });
            } else if (parsed.event === "complete") {
              onEvent({
                type: "complete",
                response: payload.response as AgentResponse,
              });
              await reader.cancel();
              return;
            }
          }
          boundary = buffer.indexOf("\n\n");
        }

        if (done) {
          throw new ApiError(
            503,
            "Agent stream ended before the completion event was received",
          );
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  examples: async () => {
    const body = await request<{ examples: RetrievalExample[] }>(
      "/api/retrieval/examples",
    );
    return body.examples;
  },

  /**
   * The persisted receipt for one search, read back out of Postgres.
   *
   * Behind the Playground's "View retrieval event" disclosure. Every number in it
   * came from `mosaic.search_event` and `mosaic.search_result_event`, not from the
   * response the browser is already holding, which is what makes it evidence.
   */
  retrievalEvent: (searchEventId: string) =>
    request<RetrievalRunResponse>(
      `/api/retrieval/events/${encodeURIComponent(searchEventId)}`,
    ),

  /** EXPLAIN ANALYZE over the run's own SQL path. A write: it persists the plan. */
  retrievalPlan: (searchEventId: string) =>
    request<RetrievalPlanResponse>(
      `/api/retrieval/events/${encodeURIComponent(searchEventId)}/plan`,
      { method: "POST" },
    ),

  evidence: (evidenceId: number) =>
    request<EvidenceRecord>(`/api/evidence/${evidenceId}`),

  toolContracts: async (surface: "agent" | "mcp" | "skill" = "agent") => {
    const body = await request<{ surface: string; tools: ToolContract[] }>(
      `/api/tools?surface=${surface}`,
    );
    return body.tools;
  },

  projection: () =>
    request<BenchmarkProjection>("/api/benchmarks/projection"),

  readiness: () =>
    request<ReadinessResponse>("/api/readiness"),

  hnswSubstrate: () => request<HnswSubstrate>("/api/hnsw/substrate"),

  hnswMeasured: () => request<HnswMeasured>("/api/hnsw/measured"),

  hnswAnchors: async () => {
    const body = await request<{ anchors: HnswProbe["anchor"][] }>(
      "/api/hnsw/anchors",
    );
    return body.anchors;
  },

  hnswNeighborhood: (anchorProductId: number, preset = "none", k = 10) => {
    const params = new URLSearchParams({ preset, k: String(k) });
    return request<HnswNeighborhood>(
      `/api/hnsw/neighborhood/${anchorProductId}?${params}`,
    );
  },

  hnswProbe: (input: HnswProbeInput, signal?: AbortSignal) =>
    request<HnswProbe>("/api/hnsw/probe", {
      method: "POST",
      signal,
      body: JSON.stringify(input),
    }),

  /**
   * The Prove step: the committed canonical evaluation artifact, read-only.
   *
   * `provenance.attributed` is the field the Retrieval Scorecard renders on;
   * the numbers travel regardless, so a caller can always show sections B,
   * C, and D even while section A is withheld pending a final-HEAD run.
   */
  scorecard: () => request<RetrievalScorecardResponse>("/api/scorecard"),
};
