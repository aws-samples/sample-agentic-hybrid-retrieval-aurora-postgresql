// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs } from "../labMissions";
import { retrievalLabOutcome } from "../labOutcome";
import { seedRun } from "../retrievalSeed";
import { RankLabCard } from "./RankLabCard";

vi.mock("../api", () => ({ api: { labsState: vi.fn(), retrievalEvent: vi.fn(), product: vi.fn() } }));
afterEach(cleanup);
const started = "2026-10-06T12:00:00Z";
const state = { lab_id: 2, entry_state: "started" as const, started_at: started, source_state: "solved" as const, database_state: "applied" as const, detail: "", completed_at: null, next_step: null };
const outcome = { label: "Verified", tone: "fixed" as const, title: "Fusion now respects source rank", detail: "Contributions reflect each position." };
const mission = coreMosaicLabs.find((item) => item.stage === "rank")!;
const wantedId = mission.target_product_ids[0];
function card() { return render(<RankLabCard mission={mission} response={seedRun} outcome={outcome} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />); }
beforeEach(() => {
  vi.mocked(api.labsState).mockReset().mockResolvedValue({ labs: [state] });
  vi.mocked(api.product).mockReset().mockResolvedValue({ title: "ViewSonic VG2756-4K" } as never);
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
  await screen.findByText("Where is the ViewSonic VG2756-4K?");
  expect(screen.queryByText(outcome.title)).toBeNull();
});
it("does not carry green state into a different search while reads are pending", async () => {
  const view = card();
  await screen.findByText(outcome.title);
  vi.mocked(api.labsState).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.retrievalEvent).mockReturnValue(new Promise(() => {}));
  view.rerender(<RankLabCard mission={mission} response={{ ...seedRun, search_event_id: "new-event" }} outcome={outcome} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />);
  await waitFor(() => expect(screen.queryByText(outcome.title)).toBeNull());
});

/** The seed's first row, moved to the wanted monitor's id at the positions the guide records. */
function monitorRun(finalRank: number, combinedRank: number) {
  const row = structuredClone(seedRun.results[0]);
  Object.assign(row, mission.filters, { product_id: wantedId, title: "ViewSonic VG2756-4K" });
  row.signals!.pre_rerank_rank = combinedRank;
  row.signals!.final_rank = finalRank;
  return { ...seedRun, query: mission.query, applied_filters: { ...mission.filters }, results: [row] };
}
it("renders the repaired verdict with the positions the live response shows", async () => {
  const run = monitorRun(5, 21);
  const real = retrievalLabOutcome(mission, run);
  expect(real.tone).toBe("fixed");
  render(<RankLabCard mission={mission} response={run} outcome={real} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />);
  const verdict = await screen.findByText(/reached reranking at combined #21/);
  expect(verdict.textContent).toContain("ViewSonic VG2756-4K");
  expect(verdict.textContent).toContain("final #5");
  expect(screen.getByRole("region").textContent).not.toMatch(/\bfirst\b/);
});
it("names the wanted product from a lookup when the run does not return it", async () => {
  const absent = { ...seedRun, results: seedRun.results.slice(1) };
  const broken = { ...outcome, tone: "broken" as const };
  render(<RankLabCard mission={mission} response={absent} outcome={broken} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />);
  await screen.findByText("Where is the ViewSonic VG2756-4K?");
  expect(api.product).toHaveBeenCalledWith(wantedId);
  expect(screen.getByText(/The ViewSonic VG2756-4K is not in these results\./)).toBeTruthy();
});
it("uses the guide's section name, not an invented stage", async () => {
  const absent = { ...seedRun, results: seedRun.results.slice(1) };
  render(<RankLabCard mission={mission} response={absent} outcome={{ ...outcome, tone: "broken" }} playgroundHref="/labs/retrieval" onSearchAgain={() => {}} />);
  await screen.findByText("Lab 2 / Send Alex’s monitor request");
  expect(screen.queryByText(/See it fail/)).toBeNull();
});
