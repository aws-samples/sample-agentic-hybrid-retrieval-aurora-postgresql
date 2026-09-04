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
import { ApiError, api } from "../api";
import type { CompletionProofResponse } from "../types";
import { CompletionProof } from "./CompletionProof";

/**
 * The block that answers "am I finished?" against Aurora rather than against
 * the participant's own reading of the screen.
 *
 * Three things it must never do, each covered below:
 *
 *   1. Grade Lab 3 off a run that does not exist. Labs 1 and 2 re-run their
 *      mission through the served path and need nothing from the caller; Lab 3
 *      grades a persisted turn, so with no `agent_run_id` on hand the honest
 *      move is to name the stage that produces one and post nothing.
 *   2. Show a green check as evidence on its own. Every failed check carries
 *      the falsifier the service served with it.
 *   3. Report an unreachable cluster as a lab failure. A 503 is a problem with
 *      the room, and telling a participant their repair failed because the
 *      database was down sends them to edit SQL that was already correct.
 */

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  api: { labProof: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const AGENT_RUN = "3f1c9d2e-0000-4000-8000-000000000001";
const EVENT_ONE = "aa11bb22-0000-4000-8000-000000000002";
const EVENT_TWO = "cc33dd44-0000-4000-8000-000000000003";

function proofFixture(
  labId: number,
  overrides: Partial<CompletionProofResponse> = {},
): CompletionProofResponse {
  return {
    lab_id: labId,
    status: "pass",
    started_at: "2026-09-04T09:00:00Z",
    finished_at: "2026-09-04T09:00:02Z",
    duration_ms: 1420,
    source_state: "solved",
    database_state: "applied",
    checks: [
      {
        name: "trigram arm contributes",
        passed: true,
        falsifier: "no candidate in the served pool carries a trigram rank",
        detail: "3 of 12 candidates entered through pg_trgm",
      },
    ],
    evidence: {
      search_event_ids: [EVENT_ONE],
      agent_run_id: null,
      evidence_ids: [],
    },
    identity: {
      source_revision: "9".repeat(40),
      retrieval_fingerprint: "a".repeat(64),
      retrieval_settings_sha256: "b".repeat(64),
      embedding_model_id: "us.cohere.embed-v4:0",
      rerank_model_id: "cohere.rerank-v3-5:0",
      dataset_manifest_sha256: "c".repeat(64),
    },
    release_baseline: {
      measured_at: "2026-08-23T21:53:32.664198Z",
      retrieval_fingerprint: "d".repeat(64),
      attributed: false,
    },
    ...overrides,
  };
}

function labBlock(labId: number): HTMLElement {
  return screen.getByTestId(`completion-proof-lab-${labId}`);
}

describe("CompletionProof", () => {
  it("offers one action and grades nothing until it is pressed", () => {
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent?.trim())).toEqual([
      "Run completion proof",
    ]);
    expect(api.labProof).not.toHaveBeenCalled();
  });

  it("proves labs 1 and 2 without a turn, and names the stage Lab 3 needs", async () => {
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId));
    render(<CompletionProof activeLab={2} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => {
      expect(api.labProof).toHaveBeenCalledWith(1, { agent_run_id: null });
      expect(api.labProof).toHaveBeenCalledWith(2, { agent_run_id: null });
    });
    // Lab 3 grades a persisted turn. Posting one with no run to name spends a
    // request to be told what the surface already knows.
    expect(api.labProof).toHaveBeenCalledTimes(2);
    expect(labBlock(3).textContent).toContain("Run the agent in 03 first");
  });

  it("grades the agent run the Reason stage produced, when there is one", async () => {
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId, {
        evidence: {
          search_event_ids: [],
          agent_run_id: labId === 3 ? AGENT_RUN : null,
          evidence_ids: labId === 3 ? [8801, 8802] : [],
        },
      }));
    render(<CompletionProof activeLab={3} agentRunId={AGENT_RUN} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() =>
      expect(api.labProof).toHaveBeenCalledWith(3, { agent_run_id: AGENT_RUN }));
    expect(api.labProof).toHaveBeenCalledTimes(3);
    await waitFor(() => expect(labBlock(3).textContent).toContain("PASS"));
    expect(labBlock(3).textContent).not.toContain("Run the agent in 03 first");
  });

  it("reports both states and the event ids a passing proof produced", async () => {
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId, {
        evidence: {
          search_event_ids: [EVENT_ONE, EVENT_TWO],
          agent_run_id: null,
          evidence_ids: [],
        },
      }));
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("PASS"));
    const block = labBlock(1);
    // A pass is three facts, not one: the checks held, the file is repaired,
    // and Aurora holds that repair.
    expect(block.textContent).toContain("source solved");
    expect(block.textContent).toContain("database applied");
    expect(block.textContent).toContain("1420 ms");
    // Short form, the same eight characters the run summary uses, so a
    // participant can match a proof to a receipt by eye.
    expect(within(block).getByText("aa11bb22")).toBeTruthy();
    expect(within(block).getByText("cc33dd44")).toBeTruthy();
    expect(block.textContent).not.toContain(EVENT_ONE);
  });

  it("shows the falsifier beside every check a failing proof reports", async () => {
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId, {
        status: labId === 1 ? "fail" : "pass",
        source_state: labId === 1 ? "broken" : "solved",
        database_state: labId === 1 ? "stale" : "applied",
        checks: labId === 1
          ? [
            {
              name: "trigram arm contributes",
              passed: false,
              falsifier: "no candidate in the served pool carries a trigram rank",
              detail: "0 of 12 candidates entered through pg_trgm",
            },
            {
              name: "target product returned",
              passed: true,
              falsifier: "product 2 is absent from the served results",
              detail: "product 2 returned at rank 4",
            },
          ]
          : proofFixture(labId).checks,
      }));
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("FAIL"));
    const block = labBlock(1);
    expect(block.textContent).toContain("trigram arm contributes");
    expect(block.textContent).toContain(
      "no candidate in the served pool carries a trigram rank",
    );
    expect(block.textContent).toContain("0 of 12 candidates entered through pg_trgm");
    // Only the checks that failed are expanded. A wall of green rows with
    // their falsifiers buries the one line the participant has to read.
    expect(block.textContent).not.toContain("product 2 returned at rank 4");
    // Paired positive: lab 2 still passed, so a failure in one lab is not
    // reported as a failure of the block.
    expect(labBlock(2).textContent).toContain("PASS");
  });

  it("reports an unreachable cluster as a problem with the room, not a lab failure", async () => {
    vi.mocked(api.labProof).mockRejectedValue(
      new ApiError(503, "found the workshop database unreachable while reading lab state"),
    );
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() =>
      expect(labBlock(1).textContent).toContain(
        "found the workshop database unreachable while reading lab state",
      ));
    // The distinction this whole test exists for.
    expect(labBlock(1).textContent).toContain("Could not run");
    expect(labBlock(1).textContent).not.toContain("FAIL");
    expect(screen.queryByText("PASS")).toBeNull();
  });

  it("tells the caller a proof finished, so the baseline beneath it re-reads", async () => {
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId));
    const onFinished = vi.fn();
    render(
      <CompletionProof activeLab={1} agentRunId={null} onFinished={onFinished} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("leaves the baseline alone when no proof could reach the service", async () => {
    // Paired falsifier for the test above. The baseline below re-reads on this
    // callback and drops what it is showing if the read fails, so announcing a
    // finish nothing finished would blank a good baseline over a 503.
    vi.mocked(api.labProof).mockRejectedValue(new ApiError(503, "database unreachable"));
    const onFinished = vi.fn();
    render(
      <CompletionProof activeLab={1} agentRunId={null} onFinished={onFinished} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("Could not run"));
    await waitFor(() => expect(labBlock(2).textContent).toContain("Could not run"));
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("explains a lab the service failed on a stale database with every check green", async () => {
    // `service/lab_proof.py` fails a lab when the source is broken or the
    // database is stale *regardless* of the checks, so the taught "repaired
    // the file, never re-applied it" case arrives here as FAIL with nothing
    // failed under it. A block that only expands failed checks reported that
    // verdict with no reason and no next step.
    vi.mocked(api.labProof).mockImplementation(async (labId) =>
      proofFixture(labId, {
        status: labId === 1 ? "fail" : "pass",
        source_state: "solved",
        database_state: labId === 1 ? "stale" : "applied",
      }));
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("FAIL"));
    const block = labBlock(1);
    expect(block.textContent).toContain(
      "The source file is repaired but the database still holds the old function."
      + " Run make db-apply-search-functions.",
    );
    // A failed lab never gets a pass's receipts: event ids under a FAIL read
    // as evidence the lab is finished.
    expect(within(block).queryByText("aa11bb22")).toBeNull();
    // Paired positive: lab 2 passed on the same press and keeps its receipt.
    expect(within(labBlock(2)).getByText("aa11bb22")).toBeTruthy();
  });

  it("names a build whose API has no proof route, without calling the lab failed", async () => {
    vi.mocked(api.labProof).mockRejectedValue(new ApiError(404, "Not Found"));
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("Could not run"));
    expect(labBlock(1).textContent).toContain(
      "This build's API serves no proof for that lab (HTTP 404).",
    );
    expect(labBlock(1).textContent).not.toContain("FAIL");
  });

  it("names a request that never reached the API as a room problem", async () => {
    // What a browser raises when the dev server is down or the proxy refused
    // the connection: the message is "Failed to fetch" and nothing else, which
    // on its own says nothing about which service failed to answer.
    vi.mocked(api.labProof).mockRejectedValue(new TypeError("Failed to fetch"));
    render(<CompletionProof activeLab={1} agentRunId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));

    await waitFor(() => expect(labBlock(1).textContent).toContain("Could not run"));
    expect(labBlock(1).textContent).toContain(
      "The completion proof could not reach the Mosaic API (Failed to fetch).",
    );
    expect(labBlock(1).textContent).not.toContain("FAIL");
  });

  it("stops the sequence when the page leaves mid-press", async () => {
    // The presses are sequential, so an unmount between two of them must end
    // the run: otherwise a participant who navigates away keeps paying for
    // retrievals on the workshop cluster, and the finish callback fires into a
    // page that is gone.
    let settle: (proof: CompletionProofResponse) => void = () => {};
    vi.mocked(api.labProof).mockImplementation(
      () =>
        new Promise<CompletionProofResponse>((resolve) => {
          settle = resolve;
        }),
    );
    const onFinished = vi.fn();
    const { unmount } = render(
      <CompletionProof activeLab={1} agentRunId={null} onFinished={onFinished} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run completion proof" }));
    await waitFor(() => expect(api.labProof).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => {
      settle(proofFixture(1));
      await Promise.resolve();
    });

    // Lab 2 was never posted, and nothing announced a finish.
    expect(api.labProof).toHaveBeenCalledTimes(1);
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("marks the lab the participant is currently in", () => {
    render(<CompletionProof activeLab={2} agentRunId={null} />);

    expect(labBlock(2).getAttribute("data-active")).toBe("true");
    expect(labBlock(1).getAttribute("data-active")).toBeNull();
    expect(labBlock(3).getAttribute("data-active")).toBeNull();
  });
});
