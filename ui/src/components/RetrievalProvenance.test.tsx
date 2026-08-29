// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type {
  RetrievalPlanResponse,
  RetrievalRunResponse,
  SearchEventRecord,
  SearchResponse,
} from "../types";
import { PersistedRunDisclosures } from "./RetrievalProvenance";

vi.mock("../api", () => ({
  api: {
    retrievalEvent: vi.fn(),
    retrievalPlan: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function response(searchEventId: string): SearchResponse {
  return {
    search_event_id: searchEventId,
    query: `query ${searchEventId}`,
    normalized_query: `query ${searchEventId}`,
    applied_filters: {},
    results: [],
    diagnostics: null,
  };
}

function persistedRun(searchEventId: string): RetrievalRunResponse {
  const run: SearchEventRecord = {
    search_event_id: searchEventId,
    occurred_at: "2026-08-28T12:00:00Z",
    session_id: null,
    query_text: `persisted ${searchEventId}`,
    normalized_query: `persisted ${searchEventId}`,
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
    total_latency_ms: 12,
    diagnostics: {},
  };
  return { run, candidates: [] };
}

function plan(searchEventId: string): RetrievalPlanResponse {
  return {
    search_event_id: searchEventId,
    plan: [{ "Node Type": `plan ${searchEventId}` }],
  };
}

function openDisclosure(label: string) {
  const summary = screen.getByText(label).closest("summary");
  if (!summary) throw new Error(`No disclosure for ${label}`);
  fireEvent.click(summary);
}

function reopenDisclosure(label: string) {
  const summary = screen.getByText(label).closest("summary");
  if (!summary) throw new Error(`No disclosure for ${label}`);
  fireEvent.click(summary);
  fireEvent.click(summary);
}

describe("PersistedRunDisclosures", () => {
  it("keeps reverse-order event and plan responses attributed to the current run", async () => {
    const eventA = deferred<RetrievalRunResponse>();
    const eventB = deferred<RetrievalRunResponse>();
    const planA = deferred<RetrievalPlanResponse>();
    const planB = deferred<RetrievalPlanResponse>();
    vi.mocked(api.retrievalEvent).mockImplementation((id) => (
      id === "run-bbbbb" ? eventB.promise : eventA.promise
    ));
    vi.mocked(api.retrievalPlan).mockImplementation((id) => (
      id === "run-bbbbb" ? planB.promise : planA.promise
    ));

    const view = render(<PersistedRunDisclosures response={response("run-aaaaa")} />);
    openDisclosure("View retrieval event");
    openDisclosure("View EXPLAIN");

    view.rerender(<PersistedRunDisclosures response={response("run-bbbbb")} />);
    openDisclosure("View retrieval event");
    openDisclosure("View EXPLAIN");

    await act(async () => {
      eventB.resolve(persistedRun("run-bbbbb"));
      planB.resolve(plan("run-bbbbb"));
    });
    expect(await screen.findByText(/persisted run-bbbbb/)).toBeTruthy();
    expect(screen.getByText(/plan run-bbbbb/)).toBeTruthy();

    await act(async () => {
      eventA.resolve(persistedRun("run-aaaaa"));
      planA.resolve(plan("run-aaaaa"));
    });
    await waitFor(() => {
      expect(screen.queryByText(/persisted run-aaaaa/)).toBeNull();
      expect(screen.queryByText(/plan run-aaaaa/)).toBeNull();
    });
  });

  it("retries a failed persisted-event read when the disclosure is reopened", async () => {
    vi.mocked(api.retrievalEvent)
      .mockRejectedValueOnce(new Error("temporary event failure"))
      .mockResolvedValueOnce(persistedRun("run-retry"));

    render(<PersistedRunDisclosures response={response("run-retry")} />);
    openDisclosure("View retrieval event");
    expect((await screen.findByRole("alert")).textContent).toContain(
      "temporary event failure",
    );

    reopenDisclosure("View retrieval event");

    expect(await screen.findByText(/persisted run-retry/)).toBeTruthy();
    expect(vi.mocked(api.retrievalEvent)).toHaveBeenCalledTimes(2);
  });

  it("retries a failed EXPLAIN capture when the disclosure is reopened", async () => {
    vi.mocked(api.retrievalPlan)
      .mockRejectedValueOnce(new Error("temporary plan failure"))
      .mockResolvedValueOnce(plan("run-retry"));

    render(<PersistedRunDisclosures response={response("run-retry")} />);
    openDisclosure("View EXPLAIN");
    expect((await screen.findByRole("alert")).textContent).toContain(
      "temporary plan failure",
    );

    reopenDisclosure("View EXPLAIN");

    expect(await screen.findByText(/plan run-retry/)).toBeTruthy();
    expect(vi.mocked(api.retrievalPlan)).toHaveBeenCalledTimes(2);
  });
});
