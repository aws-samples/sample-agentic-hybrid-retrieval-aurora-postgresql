// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { seedRun } from "../retrievalSeed";
import { RankLabCard } from "./RankLabCard";

vi.mock("../api", () => ({ api: { labsState: vi.fn(), retrievalEvent: vi.fn() } }));
afterEach(cleanup);
const started = "2026-10-06T12:00:00Z";
const state = { lab_id: 2, entry_state: "started" as const, started_at: started, source_state: "solved" as const, database_state: "applied" as const, detail: "", completed_at: null, next_step: null };
const outcome = { label: "Verified", tone: "fixed" as const, title: "Fusion now respects source rank", detail: "Contributions reflect each position." };
function card() { return render(<RankLabCard response={seedRun} outcome={outcome} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />); }
beforeEach(() => {
  vi.mocked(api.labsState).mockReset().mockResolvedValue({ labs: [state] });
  vi.mocked(api.retrievalEvent).mockReset().mockResolvedValue({ run: { occurred_at: "2026-10-06T12:01:00Z" }, candidates: [] } as never);
});
it("never credits a good result before the exercise starts", async () => {
  vi.mocked(api.labsState).mockResolvedValue({ labs: [{ ...state, entry_state: "not_started", started_at: null }] });
  card();
  await screen.findByText("Lab 2 / Not started");
  expect(screen.queryByText(outcome.title)).toBeNull();
  expect(screen.getByRole("region").className).not.toContain("fixed");
});
it("rejects a saved pre-start result even after the exercise started", async () => {
  vi.mocked(api.retrievalEvent).mockResolvedValue({ run: { occurred_at: "2026-10-06T11:59:59Z" }, candidates: [] } as never);
  card();
  await screen.findByText("This search predates Lab 2");
  expect(screen.queryByText(outcome.title)).toBeNull();
});
it("recognizes a current repair with applied SQL and inspected run time", async () => {
  card();
  await screen.findByText(outcome.title);
  expect(api.retrievalEvent).toHaveBeenCalledWith(seedRun.search_event_id);
  expect(screen.getByRole("region").className).toContain("fixed");
});
it("fails closed when the saved run cannot be inspected", async () => {
  vi.mocked(api.retrievalEvent).mockRejectedValue(new Error("offline"));
  card();
  await screen.findByText("Search timing not verified");
  expect(screen.queryByText(outcome.title)).toBeNull();
});
it("shows interrupted preparation without repair credit", async () => {
  vi.mocked(api.labsState).mockResolvedValue({ labs: [{ ...state, entry_state: "incomplete" }] });
  card();
  await screen.findByText("Lab 2 / Preparation incomplete");
  expect(screen.queryByText(outcome.title)).toBeNull();
});
it("does not credit a result when source is not applied", async () => {
  vi.mocked(api.labsState).mockResolvedValue({ labs: [{ ...state, database_state: "stale" }] });
  card();
  await screen.findByText("Does the order reflect Alex’s request?");
  expect(screen.queryByText(outcome.title)).toBeNull();
});
it("does not carry green state into a different search while reads are pending", async () => {
  const view = card();
  await screen.findByText(outcome.title);
  vi.mocked(api.labsState).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.retrievalEvent).mockReturnValue(new Promise(() => {}));
  view.rerender(<RankLabCard response={{ ...seedRun, search_event_id: "new-event" }} outcome={outcome} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />);
  await waitFor(() => expect(screen.queryByText(outcome.title)).toBeNull());
});
