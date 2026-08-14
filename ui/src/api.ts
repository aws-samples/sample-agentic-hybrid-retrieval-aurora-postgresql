import type {
  AgentConversationContext,
  AgentResponse,
  BenchmarkProjection,
  CatalogPage,
  CatalogSummary,
  ProductDetail,
  RetrievalExample,
  SearchFilters,
  SearchResponse,
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
    title: string;
    detail: string;
  }
  | { type: "answer_start"; response: AgentResponse }
  | { type: "answer_delta"; delta: string }
  | { type: "complete"; response: AgentResponse };

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

  search: (
    query: string,
    filters: SearchFilters,
    options: { limit?: number; rerank?: boolean } = {},
  ) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
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
  ) => {
    const response = await fetch("/api/agent/answer/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
          }
        }
        boundary = buffer.indexOf("\n\n");
      }

      if (done) return;
    }
  },

  examples: async () => {
    const body = await request<{ examples: RetrievalExample[] }>(
      "/api/retrieval/examples",
    );
    return body.examples;
  },

  projection: () =>
    request<BenchmarkProjection>("/api/benchmarks/projection"),
};
