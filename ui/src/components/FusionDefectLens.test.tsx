// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api";
import { seedRun } from "../retrievalSeed";
import type {
  RetrievalRunResponse,
  SearchEventRecord,
  SearchResponse,
  SearchResultEventRecord,
} from "../types";
import { FusionDefectLens } from "./FusionDefectLens";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ApiError: actual.ApiError, api: { retrievalEvent: vi.fn() } };
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function response(searchEventId: string): SearchResponse {
  return {
    search_event_id: searchEventId,
    query: searchEventId,
    normalized_query: searchEventId,
    applied_filters: {},
    results: [],
    diagnostics: {
      strategy: "rrf_fusion+rerank",
      embedding_model_id: "us.cohere.embed-v4:0",
      embedding_dimensions: 1024,
      rerank_model_id: "cohere.rerank-v3-5:0",
      rerank_status: "applied",
      retrieval_profile: seedRun.diagnostics!.retrieval_profile,
      candidate_counts: {},
      stage_timings_ms: {},
      total_latency_ms: 10,
    },
  };
}

function candidate(productId: number, fusedRank: number): SearchResultEventRecord {
  return {
    product_id: productId,
    result_rank: fusedRank,
    fts_rank: fusedRank,
    trigram_rank: null,
    semantic_rank: null,
    fused_rank: fusedRank,
    rerank_rank: fusedRank,
    scores: {},
    provenance: {},
  };
}

function persistedRun(searchEventId: string, poolSize: number): RetrievalRunResponse {
  const run: SearchEventRecord = {
    search_event_id: searchEventId,
    occurred_at: "2026-08-28T12:00:00Z",
    session_id: null,
    query_text: searchEventId,
    normalized_query: searchEventId,
    filters: {},
    retrieval_profile: {},
    source_revision: "a".repeat(40),
    embedding_model_id: "us.cohere.embed-v4:0",
    rerank_model_id: "cohere.rerank-v3-5:0",
    retrieval_strategy: "rrf_fusion+rerank",
    database_version: "18.3",
    vector_extension_version: "0.8.1",
    aurora_instance_class: null,
    hnsw_settings: {},
    candidate_counts: {},
    total_latency_ms: 10,
    diagnostics: {},
  };
  const candidates = [
    candidate(200, 1),
    candidate(100, 2),
    ...Array.from({ length: Math.max(0, poolSize - 2) }, (_, index) =>
      candidate(300 + index, 3 + index)),
  ];
  return { run, candidates };
}

function openPoolDisclosure() {
  const summary = screen
    .getByText("Check this run's full fused pool for the fusion defect")
    .closest("summary");
  if (!summary) throw new Error("Fusion disclosure was not rendered");
  fireEvent.click(summary);
}

function reopenPoolDisclosure() {
  const summary = screen
    .getByText("Check this run's full fused pool for the fusion defect")
    .closest("summary");
  if (!summary) throw new Error("Fusion disclosure was not rendered");
  fireEvent.click(summary);
  fireEvent.click(summary);
}

describe("FusionDefectLens persisted pool", () => {
  it("ignores an older pool that resolves after the current run", async () => {
    const runA = deferred<RetrievalRunResponse>();
    const runB = deferred<RetrievalRunResponse>();
    vi.mocked(api.retrievalEvent).mockImplementation((id) => (
      id === "run-b" ? runB.promise : runA.promise
    ));

    const view = render(<FusionDefectLens response={response("run-a")} />);
    openPoolDisclosure();
    view.rerender(<FusionDefectLens response={response("run-b")} />);
    openPoolDisclosure();

    await act(async () => runB.resolve(persistedRun("run-b", 2)));
    expect(await screen.findByText(/this run's 2 pooled candidates/)).toBeTruthy();

    await act(async () => runA.resolve(persistedRun("run-a", 3)));
    await waitFor(() => {
      expect(screen.getByText(/this run's 2 pooled candidates/)).toBeTruthy();
      expect(screen.queryByText(/this run's 3 pooled candidates/)).toBeNull();
    });
  });

  it("retries a transient persisted-pool failure", async () => {
    vi.mocked(api.retrievalEvent)
      .mockRejectedValueOnce(new ApiError(503, "temporary pool failure"))
      .mockResolvedValueOnce(persistedRun("run-retry", 2));

    render(<FusionDefectLens response={response("run-retry")} />);
    openPoolDisclosure();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "temporary pool failure",
    );

    reopenPoolDisclosure();

    expect(await screen.findByText(/this run's 2 pooled candidates/)).toBeTruthy();
    expect(vi.mocked(api.retrievalEvent)).toHaveBeenCalledTimes(2);
  });
});
