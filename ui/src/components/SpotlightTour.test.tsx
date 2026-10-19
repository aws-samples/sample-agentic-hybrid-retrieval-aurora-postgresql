// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_SEEN, TOUR_STORAGE_KEY, type TourStep } from "../tour";
import { SpotlightTour, TARGET_WAIT_MS } from "./SpotlightTour";

const STEPS: TourStep[] = [
  { id: "welcome", title: "Welcome", body: "Start here." },
  { id: "missing", target: "missing", title: "Missing", body: "Never on screen." },
  { id: "search", target: "search", title: "Search", body: "Type a request." },
];
const OPTIONAL: TourStep = {
  id: "optional", target: "optional", optional: true, title: "Optional", body: "Maybe absent.",
};

/** jsdom lays nothing out, so a target gets the box a browser would give it. */
function placeTarget(name: string, box = { top: 100, left: 40, width: 200, height: 40 }) {
  const element = document.createElement("div");
  element.dataset.tour = name;
  const rect = {
    ...box, x: box.left, y: box.top, right: box.left + box.width,
    bottom: box.top + box.height, toJSON: () => box,
  } as DOMRect;
  element.getBoundingClientRect = () => rect;
  element.getClientRects = () => [rect] as unknown as DOMRectList;
  document.body.append(element);
  return element;
}

function frames(ms = 50) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("SpotlightTour", () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ["requestAnimationFrame", "cancelAnimationFrame", "Date"],
    });
    window.localStorage.removeItem(TOUR_STORAGE_KEY);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    document.querySelectorAll("[data-tour]").forEach((element) => element.remove());
  });

  it("opens on a centred welcome card with Next focused", () => {
    render(<SpotlightTour open onClose={vi.fn()} steps={STEPS} />);
    frames();
    const card = screen.getByRole("dialog", { name: "Welcome" });
    expect(card.textContent).toContain("Tour · 1 of 3");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next" }));
    expect(document.querySelector(".spotlight-hole")).toBeNull();
  });

  it("passes over a control that never appears, then rings the next one", () => {
    placeTarget("search");
    render(<SpotlightTour open onClose={vi.fn()} steps={STEPS} />);
    frames();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    frames();
    expect(screen.queryByRole("dialog")).toBeNull();
    frames(TARGET_WAIT_MS + 100);
    frames();
    expect(screen.getByRole("dialog", { name: "Search" }).textContent).toContain("Tour · 3 of 3");
    const hole = document.querySelector<HTMLElement>(".spotlight-hole");
    expect(hole?.style.top).toBe("92px");
    expect(hole?.style.width).toBe("216px");
  });

  it("says Got it when only absent optional stops remain, and ends there", () => {
    const onClose = vi.fn();
    const steps = [STEPS[0], STEPS[2], OPTIONAL];
    placeTarget("search");
    render(<SpotlightTour open onClose={onClose} steps={steps} />);
    frames();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    frames();
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_SEEN);
  });

  it("passes over an absent optional stop at once", () => {
    placeTarget("search");
    render(<SpotlightTour open onClose={vi.fn()} steps={[STEPS[0], OPTIONAL, STEPS[2]]} />);
    frames();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    frames();
    expect(screen.getByRole("dialog", { name: "Search" })).toBeTruthy();
  });

  it("Skip the tour ends it and remembers", () => {
    const onClose = vi.fn();
    render(<SpotlightTour open onClose={onClose} steps={STEPS} />);
    frames();
    fireEvent.click(screen.getByRole("button", { name: "Skip the tour" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_SEEN);
  });

  it("Escape ends it and remembers", () => {
    const onClose = vi.fn();
    render(<SpotlightTour open onClose={onClose} steps={STEPS} />);
    frames();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_SEEN);
  });

  it("keeps Tab on the card's buttons and returns focus when it closes", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { rerender } = render(<SpotlightTour open onClose={vi.fn()} steps={STEPS} />);
    frames();
    const next = screen.getByRole("button", { name: "Next" });
    fireEvent.keyDown(next, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Skip the tour" }));
    rerender(<SpotlightTour open={false} onClose={vi.fn()} steps={STEPS} />);
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("shows a hint as one Tip whose ringed control still takes the click", () => {
    const key = "mosaic-hint-test";
    window.localStorage.removeItem(key);
    const target = placeTarget("search");
    const clicked = vi.fn();
    target.addEventListener("click", clicked);
    const onClose = vi.fn();
    render(<SpotlightTour hint open onClose={onClose} steps={[STEPS[2]]} storageKey={key} />);
    frames();
    const card = screen.getByRole("dialog", { name: "Search" });
    expect(card.textContent).toContain("Tip");
    expect(screen.queryByRole("button", { name: "Skip the tour" })).toBeNull();
    expect(screen.getByRole("button", { name: "Got it" })).toBeTruthy();
    // No catcher: the page under the scrim stays live, and any press closes the tip.
    expect(document.querySelector(".spotlight-catcher")).toBeNull();
    fireEvent.pointerDown(target);
    fireEvent.click(target);
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(key)).toBe(TOUR_SEEN);
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBeNull();
  });
});
