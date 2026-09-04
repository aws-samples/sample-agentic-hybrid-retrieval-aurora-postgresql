// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs } from "../labMissions";
import type { LabStateResponse } from "../types";
import { LabRail } from "./LabRail";

vi.mock("../api", () => ({
  api: {
    labsState: vi.fn(),
  },
}));

const [labOne, labTwo, labThree] = coreMosaicLabs;

const labsState: LabStateResponse = {
  labs: [
    {
      lab_id: 1,
      source_state: "broken",
      database_state: "applied",
      detail: "The trigram CTE is absent from the applied function.",
    },
    {
      lab_id: 2,
      source_state: "solved",
      database_state: "stale",
      detail: "The file is repaired; Aurora still holds the old body.",
    },
    {
      lab_id: 3,
      source_state: "broken",
      database_state: "not_applicable",
      detail: "Lab 3's seam lives in the API process.",
    },
  ],
};

describe("LabRail", () => {
  beforeEach(() => {
    vi.mocked(api.labsState).mockReset();
    vi.mocked(api.labsState).mockResolvedValue(labsState);
  });

  afterEach(cleanup);

  it("names the active lab, its three beats, and where the edit is made", async () => {
    render(<LabRail missionId={labOne.id} />);

    const rail = screen.getByRole("navigation", { name: "Lab rail" });
    expect(within(rail).getByText(labOne.title)).toBeTruthy();
    expect(
      within(rail)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
        .slice(0, 3),
    ).toEqual(["#labs-stage-retrieve", "#labs-repair-title", "#labs-stage-prove"]);
    expect(
      within(rail).getAllByRole("link").slice(0, 3).map((link) => link.textContent),
    ).toEqual(["Observe", "Repair", "Prove"]);
    expect(within(rail).getByText(labOne.participant_edit!.file)).toBeTruthy();
    expect(within(rail).getByText(labOne.participant_edit!.task)).toBeTruthy();
  });

  it("points at the next required lab, and at nothing after the last one", async () => {
    const { unmount } = render(<LabRail missionId={labOne.id} />);

    expect(
      screen.getByRole("link", { name: `Next lab: ${labTwo.title}` }).getAttribute("href"),
    ).toBe(`/labs/retrieval?example=${encodeURIComponent(labTwo.id)}`);

    unmount();
    render(<LabRail missionId={labThree.id} />);

    expect(screen.queryByText(/^Next lab:/)).toBeNull();
  });

  it("resolves a supporting check to the lab it belongs to", () => {
    // `exact-identity` is a lab-1 checkpoint rather than a lab of its own, so the
    // rail must not read as though the participant left Lab 1.
    render(<LabRail missionId="exact-identity" />);

    expect(screen.getByText(labOne.title)).toBeTruthy();
  });

  it("opens on the first required lab when no scenario is named", () => {
    render(<LabRail missionId={null} />);

    expect(screen.getByText(labOne.title)).toBeTruthy();
  });

  it("reports both places this lab can be broken, separately", async () => {
    render(<LabRail missionId={labTwo.id} />);

    // Lab 2's file is repaired while Aurora still holds the old body. One chip
    // reporting "solved" would hide exactly that.
    expect(await screen.findByText("source: solved")).toBeTruthy();
    expect(screen.getByText("database: stale")).toBeTruthy();
  });

  it("prints not applicable rather than a database verdict for Lab 3", async () => {
    render(<LabRail missionId={labThree.id} />);

    expect(await screen.findByText("database: not applicable")).toBeTruthy();
  });

  it("says the state was not checked when the state route does not answer", async () => {
    vi.mocked(api.labsState).mockReset();
    vi.mocked(api.labsState).mockRejectedValue(new Error("lab state unavailable"));
    render(<LabRail missionId={labOne.id} />);

    await waitFor(() => {
      expect(screen.getByText("source: not checked")).toBeTruthy();
    });
    expect(screen.getByText("database: not checked")).toBeTruthy();
    // And never a guess: a failed read must not print a verdict of its own.
    expect(screen.queryByText(/source: (solved|broken)/)).toBeNull();
  });
});
