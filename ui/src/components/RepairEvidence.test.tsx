// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import {
  NO_BEFORE_EVENT,
  RANK_UNCHANGED_REASSURANCE,
  SUSPICIOUS_GAP_CAUTION,
} from "../repairEvidence";
import type {
  RetrievalRunResponse,
  SearchEventRecord,
  SearchResultEventRecord,
} from "../types";
import { RepairEvidence } from "./RepairEvidence";

/**
 * The three gate-critical behaviors, at the surface a participant actually reads:
 *
 *   1. the measured Lab 1 pair's arm delta (trigram 0 -> 1) renders, and the
 *      unchanged fused/final rank is framed as confirmation, never as failure;
 *   2. a large fused-to-final gap (the measured 675825de shape) renders its
 *      caution; a small one does not;
 *   3. a missing before renders the honest empty state, and a bad id renders an
 *      error rather than an empty frame -- and never reaches the network.
 */

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ApiError: actual.ApiError, api: { retrievalEvent: vi.fn() } };
});

afterEach(() => {
  cleanup();
  vi.mocked(api.retrievalEvent).mockReset();
});

function runRecord(overrides: Partial<SearchEventRecord> = {}): SearchEventRecord {
  return {
    search_event_id: "00000000-0000-4000-8000-000000000000",
    occurred_at: "2026-08-23T21:09:45.604925Z",
    session_id: null,
    query_text: "noice cancelng hedfones",
    normalized_query: "noice cancelng hedfones",
    filters: {},
    retrieval_profile: {},
    source_revision: "d8895cd6d88d20640d5fa518486668e98e788224",
    embedding_model_id: "us.cohere.embed-v4:0",
    rerank_model_id: "cohere.rerank-v3-5:0",
    retrieval_strategy: "rrf_fusion+rerank+exact_sku_preservation",
    database_version: "18.3",
    vector_extension_version: "0.8.1",
    aurora_instance_class: null,
    hnsw_settings: {},
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 0, semantic_in_pool: 49 },
    total_latency_ms: 785,
    diagnostics: {},
    ...overrides,
  };
}

function candidate(
  overrides: Partial<SearchResultEventRecord> = {},
): SearchResultEventRecord {
  return {
    product_id: 2,
    result_rank: 1,
    fts_rank: 1,
    trigram_rank: null,
    semantic_rank: null,
    fused_rank: 1,
    rerank_rank: 1,
    scores: {},
    provenance: {},
    ...overrides,
  };
}

function run(
  eventOverrides: Partial<SearchEventRecord>,
  candidates: SearchResultEventRecord[],
): RetrievalRunResponse {
  return { run: runRecord(eventOverrides), candidates };
}

const BEFORE_ID = "9f92f8cc-efc2-4d81-a94a-69638d050282";
const AFTER_ID = "9614ed9b-4ceb-4aad-9276-4e69af2231b9";

const LAB1_BEFORE = run(
  {
    search_event_id: BEFORE_ID,
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 0, semantic_in_pool: 49 },
  },
  [candidate({ trigram_rank: null })],
);

const LAB1_AFTER = run(
  {
    search_event_id: AFTER_ID,
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 1, semantic_in_pool: 49 },
  },
  [candidate({ trigram_rank: 1 })],
);

function mockEventsByid(events: Record<string, RetrievalRunResponse>) {
  vi.mocked(api.retrievalEvent).mockImplementation(async (id: string) => {
    const found = events[id];
    if (!found) throw new ApiError(404, "Search event not found");
    return found;
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function cellsInRowFor(labelText: string): string[] {
  const label = screen.getByText(labelText);
  const row = label.closest("tr");
  if (!row) throw new Error(`No <tr> ancestor for "${labelText}"`);
  return Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent ?? "");
}

async function pressCompare() {
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Comparing" })).toBeNull());
}

describe("RepairEvidence — measured Lab 1 pair", () => {
  it("keeps the inputs, action, and helper on one centered content measure", () => {
    const { container } = render(
      <RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />,
    );
    const content = container.querySelector(".labs-repair-content");
    const form = content?.querySelector(".labs-repair-form");
    const helper = content?.querySelector(".labs-repair-hint");

    expect(content).toBeTruthy();
    expect(form?.children).toHaveLength(3);
    expect(form?.children[0].textContent).toContain("Before");
    expect(form?.children[1].textContent).toContain("After");
    expect(form?.children[2].textContent).toContain("Compare");
    expect(helper).toBeTruthy();
  });

  it("shows the trigram participation delta and frames the unchanged rank as confirmation", async () => {
    mockEventsByid({ [BEFORE_ID]: LAB1_BEFORE, [AFTER_ID]: LAB1_AFTER });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={null} />);

    fireEvent.change(screen.getByLabelText("Before search_event_id"), {
      target: { value: BEFORE_ID },
    });
    fireEvent.change(screen.getByLabelText("After search_event_id"), {
      target: { value: AFTER_ID },
    });
    await pressCompare();

    expect(cellsInRowFor("Close spelling")).toEqual(["0", "1", "not in pool", "#1"]);

    // Assert the framing text is present verbatim, not just the numbers, and
    // that no failure-shaped wording sits next to it.
    expect(await screen.findByText(RANK_UNCHANGED_REASSURANCE)).toBeTruthy();
    expect(screen.queryByText(/failed/i)?.textContent).toBe(RANK_UNCHANGED_REASSURANCE);
    expect(screen.getByText("Before reranking").closest(".labs-figure")?.textContent)
      .toContain("#1 → #1");
    expect(screen.getByText("Final position").closest(".labs-figure")?.textContent)
      .toContain("#1 → #1");

    // The zero-gap shape must not raise the caution.
    expect(screen.queryByText(SUSPICIOUS_GAP_CAUTION)).toBeNull();
  });

  it("is independent of session metadata that carries no retrieval information", async () => {
    const before = run(
      {
        search_event_id: BEFORE_ID,
        session_id: "unrelated-session",
        occurred_at: "2020-01-01T00:00:00Z",
        candidate_counts: LAB1_BEFORE.run.candidate_counts,
      },
      LAB1_BEFORE.candidates,
    );
    const after = run(
      {
        search_event_id: AFTER_ID,
        session_id: "canonical-release-eval",
        occurred_at: "2099-12-31T23:59:59Z",
        candidate_counts: LAB1_AFTER.run.candidate_counts,
      },
      LAB1_AFTER.candidates,
    );
    mockEventsByid({ [BEFORE_ID]: before, [AFTER_ID]: after });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={null} />);

    fireEvent.change(screen.getByLabelText("Before search_event_id"), {
      target: { value: BEFORE_ID },
    });
    fireEvent.change(screen.getByLabelText("After search_event_id"), {
      target: { value: AFTER_ID },
    });
    await pressCompare();

    expect(cellsInRowFor("Close spelling")).toEqual(["0", "1", "not in pool", "#1"]);
    expect(await screen.findByText(RANK_UNCHANGED_REASSURANCE)).toBeTruthy();
  });
});

describe("RepairEvidence — pinned baseline", () => {
  it("compares the pinned baseline against the latest run without being asked", async () => {
    // The panel used to require two UUIDs pasted by hand, from a file the
    // participant had to remember to save. The Playground now knows both ids, so
    // the comparison that is the whole point of the panel runs on its own.
    mockEventsByid({ [BEFORE_ID]: LAB1_BEFORE, [AFTER_ID]: LAB1_AFTER });
    render(
      <RepairEvidence baselineSearchEventId={BEFORE_ID} latestSearchEventId={AFTER_ID} />,
    );

    expect(await screen.findByText(RANK_UNCHANGED_REASSURANCE)).toBeTruthy();
    expect(cellsInRowFor("Close spelling")).toEqual(["0", "1", "not in pool", "#1"]);
    expect(vi.mocked(api.retrievalEvent).mock.calls.map(([id]) => id).sort())
      .toEqual([BEFORE_ID, AFTER_ID].sort());
  });

  it("keeps the pasted ids for other runs behind a closed disclosure", () => {
    render(
      <RepairEvidence baselineSearchEventId={BEFORE_ID} latestSearchEventId={AFTER_ID} />,
    );

    const disclosure = screen.getByText("Compare other runs").closest("details");
    expect(disclosure).toBeTruthy();
    expect((disclosure as HTMLDetailsElement).open).toBe(false);
    expect(disclosure!.contains(screen.getByLabelText("Before search_event_id"))).toBe(true);
    expect(disclosure!.contains(screen.getByLabelText("After search_event_id"))).toBe(true);
    // The old placeholder named a file path the workshop no longer writes.
    expect(screen.getByLabelText("Before search_event_id").getAttribute("placeholder"))
      .toBe("paste a search_event_id");
  });

  it("does not compare a baseline against itself", async () => {
    // On arrival from Shop the pinned run and the latest run are the same event.
    // Diffing it against itself would report a repair where nothing has happened.
    mockEventsByid({ [AFTER_ID]: LAB1_AFTER });
    render(
      <RepairEvidence baselineSearchEventId={AFTER_ID} latestSearchEventId={AFTER_ID} />,
    );

    await waitFor(() => expect(screen.getByText("Repair evidence")).toBeTruthy());
    expect(vi.mocked(api.retrievalEvent)).not.toHaveBeenCalled();
    expect(screen.queryByText("Close spelling")).toBeNull();
  });

  it("re-compares when the Playground re-pins the baseline", async () => {
    const other = run(
      {
        search_event_id: "3f0a9d1c-6b2e-4c7a-8d51-2e9f4a6b7c80",
        candidate_counts: LAB1_AFTER.run.candidate_counts,
      },
      [candidate({ product_id: 404, trigram_rank: 1 })],
    );
    mockEventsByid({
      [BEFORE_ID]: LAB1_BEFORE,
      [AFTER_ID]: LAB1_AFTER,
      "3f0a9d1c-6b2e-4c7a-8d51-2e9f4a6b7c80": other,
    });
    const { rerender } = render(
      <RepairEvidence baselineSearchEventId={BEFORE_ID} latestSearchEventId={AFTER_ID} />,
    );
    expect(await screen.findByText(/product #2\b/)).toBeTruthy();

    rerender(
      <RepairEvidence
        baselineSearchEventId={AFTER_ID}
        latestSearchEventId="3f0a9d1c-6b2e-4c7a-8d51-2e9f4a6b7c80"
      />,
    );

    expect(await screen.findByText(/product #404/)).toBeTruthy();
  });

  it("never spends a request on an id that is not shaped like one", async () => {
    // The Playground's run ids are real event ids, but an automatic comparison
    // must not raise a paste error for something the participant never pasted.
    render(
      <RepairEvidence baselineSearchEventId="first-run" latestSearchEventId="latest-run" />,
    );

    await waitFor(() => expect(screen.getByText("Repair evidence")).toBeTruthy());
    expect(vi.mocked(api.retrievalEvent)).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("RepairEvidence — fused-to-final gap", () => {
  it("renders the caution for the measured 675825de shape (fused 49 -> final 1)", async () => {
    const after = run(
      { candidate_counts: { fused_pool: 50, fts_in_pool: 18, trigram_in_pool: 18, semantic_in_pool: 19 } },
      [candidate({
        product_id: 211896,
        result_rank: 1,
        fused_rank: 49,
        fts_rank: 73,
        trigram_rank: null,
        semantic_rank: 114,
      })],
    );
    mockEventsByid({ [AFTER_ID]: after });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    await pressCompare();

    expect(await screen.findByText(SUSPICIOUS_GAP_CAUTION)).toBeTruthy();
    expect(screen.getByText("Before reranking").closest(".labs-figure")?.textContent)
      .toContain("no earlier run → #49");
    expect(screen.getByText("Final position").closest(".labs-figure")?.textContent)
      .toContain("no earlier run → #1");
  });

  it("does not render the caution for a small fused-to-final move", async () => {
    mockEventsByid({ [AFTER_ID]: LAB1_AFTER });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    await pressCompare();

    expect(await screen.findByText("Repair evidence")).toBeTruthy();
    expect(screen.queryByText(SUSPICIOUS_GAP_CAUTION)).toBeNull();
  });
});

describe("RepairEvidence — missing before and bad ids", () => {
  it("renders the honest missing-before state without blocking the after-only evidence", async () => {
    mockEventsByid({ [AFTER_ID]: LAB1_AFTER });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    await pressCompare();

    expect(await screen.findByText(NO_BEFORE_EVENT)).toBeTruthy();
    // Not an empty frame: the after run's own arm participation still renders.
    expect(cellsInRowFor("Close spelling")).toEqual(["no earlier run", "1", "no earlier run", "#1"]);
    // No fabricated baseline: no "0 ->" numeral appears for the before side.
    expect(screen.queryByText("0")).toBeNull();
  });

  it("rejects a malformed before id without ever calling the API for it", async () => {
    mockEventsByid({ [AFTER_ID]: LAB1_AFTER });
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    fireEvent.change(screen.getByLabelText("Before search_event_id"), {
      target: { value: "not-a-uuid" },
    });
    await pressCompare();

    expect(await screen.findByText(/doesn't look like a search_event_id/i)).toBeTruthy();
    expect(vi.mocked(api.retrievalEvent)).not.toHaveBeenCalledWith("not-a-uuid");
    // Still not an empty frame: the after-only evidence still renders alongside
    // the error.
    expect(screen.getByText("Repair evidence")).toBeTruthy();
    expect(cellsInRowFor("Close spelling")[1]).toBe("1");
  });

  it("renders a clear error for a well-formed but unknown after id, not an empty frame", async () => {
    mockEventsByid({});
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    await pressCompare();

    expect(await screen.findByText(new RegExp(`No retrieval event found for ${AFTER_ID}`)))
      .toBeTruthy();
    // No dormant "not attempted yet" copy left over, and no evidence table.
    expect(screen.queryByText(/paste the before id you saved/i)).toBeNull();
    expect(screen.queryByText("Close spelling")).toBeNull();
  });
});

describe("RepairEvidence — request attribution", () => {
  it("keeps reverse-order comparisons attached to the ids currently in the form", async () => {
    const first = deferred<RetrievalRunResponse>();
    const second = deferred<RetrievalRunResponse>();
    vi.mocked(api.retrievalEvent).mockImplementation((id: string) => (
      id === AFTER_ID ? second.promise : first.promise
    ));
    const firstId = BEFORE_ID;
    const firstRun = run(
      { search_event_id: firstId },
      [candidate({ product_id: 101 })],
    );
    const secondRun = run(
      { search_event_id: AFTER_ID },
      [candidate({ product_id: 202 })],
    );
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={null} />);

    fireEvent.change(screen.getByLabelText("After search_event_id"), {
      target: { value: firstId },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    fireEvent.change(screen.getByLabelText("After search_event_id"), {
      target: { value: AFTER_ID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    await act(async () => second.resolve(secondRun));
    expect(await screen.findByText(/product #202/)).toBeTruthy();

    await act(async () => first.resolve(firstRun));
    await waitFor(() => {
      expect(screen.getByText(/product #202/)).toBeTruthy();
      expect(screen.queryByText(/product #101/)).toBeNull();
    });
  });

  it("retries a transient comparison failure", async () => {
    vi.mocked(api.retrievalEvent)
      .mockRejectedValueOnce(new Error("temporary comparison failure"))
      .mockResolvedValueOnce(LAB1_AFTER);
    render(<RepairEvidence baselineSearchEventId={null} latestSearchEventId={AFTER_ID} />);

    await pressCompare();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "temporary comparison failure",
    );

    await pressCompare();

    expect(await screen.findByText(/product #2/)).toBeTruthy();
    expect(screen.queryByText("temporary comparison failure")).toBeNull();
    expect(vi.mocked(api.retrievalEvent)).toHaveBeenCalledTimes(2);
  });
});
