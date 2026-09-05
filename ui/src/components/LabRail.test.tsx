// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

  const STAGE_LABELS = ["Retrieve", "Rank", "Reason", "Prove"];
  const STAGE_HREFS = [
    "#labs-stage-retrieve",
    "#labs-stage-rank",
    "#labs-stage-reason",
    "#labs-stage-prove",
  ];

  it("names the active lab, the four stages, and where the edit is made", async () => {
    render(<LabRail missionId={labOne.id} />);

    const rail = screen.getByRole("navigation", { name: "Lab rail" });
    expect(within(rail).getByText(labOne.title)).toBeTruthy();
    expect(
      within(rail)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
        .slice(0, 4),
    ).toEqual(STAGE_HREFS);
    // Four links in the list, not four among more: the rail used to carry a
    // three-beat vocabulary of its own for the same sections the page already
    // draws under the workshop's own words, and nothing of it may survive.
    expect(
      [...rail.querySelectorAll(".labs-rail-stages a")].map((link) => link.textContent),
    ).toEqual(STAGE_LABELS);
    // No hint lines under them either: the stage name is the description.
    expect(rail.querySelector(".labs-rail-stages small")).toBeNull();
    expect(within(rail).getByText(labOne.participant_edit!.file)).toBeTruthy();
    expect(within(rail).getByText(labOne.participant_edit!.task)).toBeTruthy();
  });

  it("marks the stage the active lab is about, and only that one", () => {
    // Every lab offers all four links, so the only thing distinguishing Lab 2's
    // rail from Lab 1's is which of them is marked current. Getting that from a
    // module constant rather than from the mission would put Lab 2's participant
    // on the retrieval stage.
    const expected: Array<[string, string]> = [
      [labOne.id, "Retrieve"],
      [labTwo.id, "Rank"],
      [labThree.id, "Reason"],
    ];

    // Witness, independent of the loop: three cases, one per required lab, and
    // the three of them really do declare three different stages. A manifest
    // that collapsed two labs onto one stage would make this test vacuous.
    expect(expected.length).toBe(3);
    expect(coreMosaicLabs.map((lab) => lab.stage)).toEqual([
      "retrieve",
      "rank",
      "reason",
    ]);

    for (const [missionId, current] of expected) {
      const { unmount } = render(<LabRail missionId={missionId} />);
      const rail = screen.getByRole("navigation", { name: "Lab rail" });

      // The same four destinations in every lab, in pipeline order.
      expect(
        within(rail)
          .getAllByRole("link")
          .slice(0, 4)
          .map((link) => link.getAttribute("href")),
      ).toEqual(STAGE_HREFS);
      expect(
        [...rail.querySelectorAll('[aria-current="step"]')].map(
          (link) => link.textContent,
        ),
      ).toEqual([current]);

      unmount();
    }
  });

  it("points at the next required lab, and at nothing after the last one", async () => {
    const { unmount } = render(<LabRail missionId={labOne.id} />);

    expect(
      screen.getByRole("link", { name: `Next lab: ${labTwo.title}` }).getAttribute("href"),
    ).toBe(`/labs/retrieval?example=${encodeURIComponent(labTwo.id)}`);

    unmount();
    const second = render(<LabRail missionId={labTwo.id} />);

    // Lab 3 is asked on Shop rather than here, so its link leaves this route.
    const toLabThree = screen
      .getByRole("link", { name: `Next lab: ${labThree.title}` })
      .getAttribute("href")!;
    expect(toLabThree.startsWith("/catalog?")).toBe(true);
    const carried = new URLSearchParams(toLabThree.slice("/catalog?".length));
    expect(carried.get("ask")).toBe("1");
    expect(carried.get("mission")).toBe(labThree.id);
    expect(carried.get("q")).toBe(labThree.query);

    second.unmount();
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

  it("condenses while stuck under the site header and expands when it scrolls free", async () => {
    // Sticky under the header, the full rail cost a quarter of a 768px viewport
    // for the rest of the page. It is observed against a root shrunk by the
    // header's height, so it is fully visible until the header clips its top
    // edge; a long rail clipped at the bottom of a short screen is not stuck.
    let callback: IntersectionObserverCallback | null = null;
    class StubIntersectionObserver {
      constructor(observe: IntersectionObserverCallback) {
        callback = observe;
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal("IntersectionObserver", StubIntersectionObserver);
    const entry = (intersectionRatio: number, top: number) =>
      [
        { intersectionRatio, boundingClientRect: { top }, rootBounds: { top: 71 } },
      ] as unknown as IntersectionObserverEntry[];
    const observer = {} as IntersectionObserver;
    try {
      render(<LabRail missionId={labOne.id} />);
      await screen.findByText("source: broken");
      const rail = screen.getByRole("navigation", { name: "Lab rail" });
      expect(rail.className).toBe("labs-rail");
      expect(callback).not.toBeNull();

      act(() => callback!(entry(0.96, 70), observer));
      expect(rail.className).toBe("labs-rail is-stuck");
      // A condensed rail reports a new ratio; it is still stuck.
      act(() => callback!(entry(0.9, 70), observer));
      expect(rail.className).toBe("labs-rail is-stuck");

      act(() => callback!(entry(1, 140), observer));
      expect(rail.className).toBe("labs-rail");

      // Clipped at the bottom, not the top: not stuck.
      act(() => callback!(entry(0.5, 640), observer));
      expect(rail.className).toBe("labs-rail");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
