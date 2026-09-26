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

const allBroken: LabStateResponse = {
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

  it("names the three required labs as one sequence, in order", async () => {
    vi.mocked(api.labsState).mockResolvedValue(allBroken);
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

  it("invites a fresh participant into Lab 1 before any lab state is known", () => {
    vi.mocked(api.labsState).mockReturnValue(new Promise(() => {}));
    render(<WorkshopProgress />);

    const cta = screen.getByRole("link", { name: `Start ${labOne.title}` });
    expect(cta.getAttribute("href")).toBe(retrievalExampleHref(labOne));
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
      expect(screen.getByRole("link", { name: `Start ${labOne.title}` })).toBeTruthy();
    });
    expect(screen.queryByText("Repaired")).toBeNull();
    expect(screen.queryByText("Needs repair")).toBeNull();
    expect(screen.getAllByText("Not checked")).toHaveLength(3);
  });

  it("keeps every lab and the primary action reachable as a plain, focusable link", async () => {
    vi.mocked(api.labsState).mockResolvedValue(allBroken);
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
