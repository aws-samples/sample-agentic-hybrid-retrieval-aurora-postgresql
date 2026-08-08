import type {
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

export const api = {
  summary: () => request<CatalogSummary>("/api/catalog/summary"),

  catalog: (filters: SearchFilters, offset = 0, limit = 24, sort = "featured") => {
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

  agent: (question: string, filters: SearchFilters) =>
    request<AgentResponse>("/api/agent/answer", {
      method: "POST",
      body: JSON.stringify({
        question,
        filters,
        result_limit: 6,
      }),
    }),

  examples: async () => {
    const body = await request<{ examples: RetrievalExample[] }>(
      "/api/retrieval/examples",
    );
    return body.examples;
  },

  projection: () =>
    request<BenchmarkProjection>("/api/benchmarks/projection"),
};
