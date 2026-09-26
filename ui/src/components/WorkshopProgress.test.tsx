// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs, retrievalExampleHref } from "../labMissions";
import type { LabStateRecord, LabStateResponse } from "../types";
import { WorkshopProgress, workshopLabStatus } from "./WorkshopProgress";

vi.mock("../api", () => ({
  api: {
    labsState: vi.fn(),
  },
}));

const [labOne, labTwo, labThree] = coreMosaicLabs;

function state(
  labId: number,
  sourceState: LabStateRecord["source_state"],
  databaseState: LabStateRecord["database_state"],
): LabStateRecord {
  return { lab_id: labId, source_state: sourceState, database_state: databaseState, detail: "" };
}

/**
 * The ordinary steady state for a room that has not touched anything yet.
 *
 * `source_state: "broken"` is what a never-attempted lab reports *and* what a
 * mid-repair one reports -- the API carries no fact that tells the two apart
 * -- so this fixture is deliberately named for what it actually represents:
 * a settled read, not a loading placeholder.
 */
const freshRoom: LabStateResponse = {
  labs: [
    state(1, "broken", "applied"),
    state(2, "broken", "not_applicable"),
    state(3, "broken", "not_applicable"),
  ],
};

describe("workshopLabStatus", () => {
  it("requires both a repaired file and an applied database", () => {
    expect(workshopLabStatus(null)).toBe("not_checked");
    expect(workshopLabStatus(state(1, "broken", "applied"))).toBe("needs_repair");
    // The taught failure mode: the file is repaired but Aurora still holds the
    // old function. A single "solved" flag would read this as done.
    expect(workshopLabStatus(state(1, "solved", "stale"))).toBe("needs_repair");
    expect(workshopLabStatus(state(1, "solved", "applied"))).toBe("repaired");
    expect(workshopLabStatus(state(1, "solved", "not_applicable"))).toBe("repaired");
  });
});

describe("WorkshopProgress", () => {
  beforeEach(() => {
    vi.mocked(api.labsState).mockReset();
  });

  afterEach(cleanup);

  it("renders every lab as 'Not checked' before the first read settles", () => {
    // Deliberately synchronous and unresolved: this is the render React commits
    // before `useLabStates`'s effect has had a turn of the microtask queue to
    // resolve, not a claim about what the panel says once data has arrived.
    vi.mocked(api.labsState).mockReturnValue(new Promise(() => {}));
    render(<WorkshopProgress />);

    const section = screen.getByRole("region", { name: "Retrieve → Rank → Reason" });
    expect(within(section).getByText("Required workshop path")).toBeTruthy();

    const items = within(section).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items.map((item) => within(item).getByRole("link").textContent)).toEqual([
      `1${labOne.title}Not checked`,
      `2${labTwo.title}Not checked`,
      `3${labThree.title}Not checked`,
    ]);
  });

  it("opens 'Open Lab 1', not 'Continue', once a never-touched room's real state has loaded", async () => {
    // Regression for the bug this test replaced: mocking a promise that never
    // resolves only exercised the loading flicker, so the real steady state
    // -- every lab reporting "broken" once `/api/labs/state` actually answers
    // -- was never asserted. "broken" also flips `workshopLabStatus` to
    // "needs_repair", not "not_checked", the moment the read settles, and the
    // CTA has no repaired lab yet to justify "Continue".
    vi.mocked(api.labsState).mockResolvedValue(freshRoom);
    render(<WorkshopProgress />);

    const cta = await screen.findByRole("link", { name: `Open ${labOne.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labOne));
    expect(screen.queryByRole("link", { name: `Start ${labOne.title}` })).toBeNull();
    expect(screen.queryByRole("link", { name: `Continue ${labOne.title}` })).toBeNull();
    // Every lab reads "Needs repair", not "Not checked", once the read settles.
    expect(within(screen.getByRole("region", { name: "Retrieve → Rank → Reason" })).getAllByText("Needs repair")).toHaveLength(3);
  });

  it("points the primary action at the first lab that is not yet repaired", async () => {
    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        state(1, "solved", "applied"),
        state(2, "broken", "not_applicable"),
        state(3, "broken", "not_applicable"),
      ],
    });
    render(<WorkshopProgress />);

    const cta = await screen.findByRole("link", { name: `Continue ${labTwo.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labTwo));
    // Lab 1 reports repaired without being asked twice.
    expect(await screen.findByText("Repaired")).toBeTruthy();
    // aria-current marks the lab that is actually next, not the first one.
    // The lab number is `aria-hidden`, so the accessible name carries only
    // the title and status -- `textContent` (checked above) still has it.
    const nextLink = screen.getByRole("link", { name: `${labTwo.title}Needs repair` });
    expect(nextLink.getAttribute("aria-current")).toBe("step");
    const firstLink = screen.getByRole("link", { name: `${labOne.title}Repaired` });
    expect(firstLink.getAttribute("aria-current")).toBeNull();
  });

  it("says 'Continue', not 'Open', for Lab 2 even when Lab 1 is the one still broken", async () => {
    // An out-of-order repair (Lab 2's SQL applied while Lab 1's file is still
    // broken) is an unusual room, not an impossible one. Once *any* lab is
    // repaired the participant has plainly started, so nothing downstream may
    // read "Open" -- only the untouched-sequence case may.
    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        state(1, "broken", "applied"),
        state(2, "solved", "applied"),
        state(3, "broken", "not_applicable"),
      ],
    });
    render(<WorkshopProgress />);

    const cta = await screen.findByRole("link", { name: `Continue ${labOne.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labOne));
  });

  it("routes Lab 3 into Shop, the same way LabRail's next-lab link does", async () => {
    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        state(1, "solved", "applied"),
        state(2, "solved", "applied"),
        state(3, "broken", "not_applicable"),
      ],
    });
    render(<WorkshopProgress />);

    const cta = await screen.findByRole("link", { name: `Continue ${labThree.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labThree));
    expect(cta.getAttribute("href")!.startsWith("/catalog?")).toBe(true);
  });

  it("offers to review once every required lab is repaired", async () => {
    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        state(1, "solved", "applied"),
        state(2, "solved", "applied"),
        state(3, "solved", "not_applicable"),
      ],
    });
    render(<WorkshopProgress />);

    const cta = await screen.findByRole("link", { name: "Review your labs" });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labOne));
    expect(within(screen.getByRole("region", { name: "Retrieve → Rank → Reason" })).getAllByText("Repaired")).toHaveLength(3);
  });

  it("never guesses a status when the lab-state read fails", async () => {
    vi.mocked(api.labsState).mockRejectedValue(new Error("lab state unavailable"));
    render(<WorkshopProgress />);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: `Open ${labOne.title}` })).toBeTruthy();
    });
    expect(screen.queryByText("Repaired")).toBeNull();
    expect(screen.queryByText("Needs repair")).toBeNull();
    expect(screen.getAllByText("Not checked")).toHaveLength(3);
  });

  it("shows a distinct, reloadable message when the lab-state read fails, and keeps the entry usable", async () => {
    vi.mocked(api.labsState).mockRejectedValue(new Error("lab state unavailable"));
    render(<WorkshopProgress />);

    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("Lab state unavailable; reload to retry.");
    // Not the same message a fresh, un-fetched panel would also show while
    // loading -- a participant deciding whether to reload needs the two told
    // apart, not both spelled "Not checked".
    expect(screen.getAllByText("Not checked")).toHaveLength(3);
    // The panel keeps a real, working action rather than going dead on error.
    const cta = screen.getByRole("link", { name: `Open ${labOne.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labOne));
  });

  it("shows no failure line while a read is only in flight, or once one has settled", async () => {
    vi.mocked(api.labsState).mockResolvedValue(freshRoom);
    render(<WorkshopProgress />);

    expect(screen.queryByText(/Lab state unavailable/)).toBeNull();
    await screen.findByRole("link", { name: `Open ${labOne.title}` });
    expect(screen.queryByText(/Lab state unavailable/)).toBeNull();
  });

  it("keeps every lab and the primary action reachable as a plain, focusable link", async () => {
    vi.mocked(api.labsState).mockResolvedValue(freshRoom);
    render(<WorkshopProgress />);

    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThanOrEqual(4);
    for (const link of links) {
      expect(link.tagName).toBe("A");
      expect(link.getAttribute("tabindex")).toBeNull();
      expect(link.getAttribute("href")).toBeTruthy();
    }
  });
});
