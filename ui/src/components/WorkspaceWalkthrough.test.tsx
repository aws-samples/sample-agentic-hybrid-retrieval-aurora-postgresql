// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorialStories } from "../discoverContent";
import { WorkspaceWalkthrough } from "./WorkspaceWalkthrough";

let showCaption: (visible: boolean) => void;
let showImage: (visible: boolean) => void;
let motionChange: (() => void) | undefined;
let reduceMotion = false;

function advance(milliseconds: number) {
  act(() => { vi.advanceTimersByTime(milliseconds); });
}

function ready() {
  fireEvent.load(screen.getByAltText(/^The vision for Alex/));
  act(() => { showCaption(true); showImage(true); });
}

function next() {
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
}

describe("WorkspaceWalkthrough", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    reduceMotion = false;
    motionChange = undefined;
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      get matches() { return reduceMotion; },
      addEventListener: (_type: string, callback: () => void) => { motionChange = callback; },
      removeEventListener: vi.fn(),
    })));
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        const update = (visible: boolean) => this.callback([
          { target, isIntersecting: visible, intersectionRatio: visible ? 1 : 0 } as IntersectionObserverEntry,
        ], this as unknown as IntersectionObserver);
        if (target.tagName === "FIGCAPTION") showCaption = update;
        else showImage = update;
      }
      disconnect() {}
    });
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("waits for the explanation and image, advances every four seconds, then stops at the vision", () => {
    render(<WorkspaceWalkthrough real />);
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    act(() => showCaption(true));
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    fireEvent.load(screen.getByAltText(/^The vision for Alex/));
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    act(() => showImage(true));
    advance(3_999);
    expect(screen.getByRole("heading", { name: "Desk. Laptop. A place to start." })).toBeTruthy();
    advance(1);
    expect(screen.getByRole("heading", { name: "Help him be heard." })).toBeTruthy();
    advance(4_000);
    expect(screen.getByRole("heading", { name: "Make long days comfortable." })).toBeTruthy();
    advance(4_000);
    expect(screen.getByRole("heading", { name: "Put code and docs side by side." })).toBeTruthy();
    advance(4_000);
    expect(screen.getByRole("link", { name: "Start with clearer calls" })).toBeTruthy();
    advance(60_000);
    expect(screen.getByLabelText("Step 5 of 5")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pause walkthrough" })).toBeNull();
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();
  });

  it("offers Next and Pause without clickable step markers, then lets Replay restart the introduction", () => {
    render(<WorkspaceWalkthrough real />);
    ready();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Previous step" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Workspace walkthrough steps" })).toBeNull();
    next();
    advance(30_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play walkthrough" })).toBeTruthy();
    next();
    next();
    next();
    expect(screen.getByLabelText("Step 5 of 5")).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    advance(4_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
  });

  it("honors Pause and Play without a focused playback button reversing the action", () => {
    render(<WorkspaceWalkthrough real />);
    ready();
    const pause = screen.getByRole("button", { name: "Pause walkthrough" });
    fireEvent.focus(pause);
    fireEvent.click(pause);
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play walkthrough" }));
    advance(4_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
  });

  it("ignores a resting pointer but holds the explanation off screen or in a hidden tab", () => {
    render(<WorkspaceWalkthrough real />);
    ready();
    const walkthrough = screen.getByRole("figure", { name: "Alex’s workspace walkthrough" });
    fireEvent.pointerEnter(walkthrough);
    advance(4_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    act(() => showCaption(false));
    advance(30_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    act(() => showCaption(true));
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    advance(30_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    fireEvent(document, new Event("visibilitychange"));
    advance(4_000);
    expect(screen.getByLabelText("Step 3 of 5")).toBeTruthy();
  });

  it("stops when a keyboard user focuses Next or a destination", () => {
    render(<WorkspaceWalkthrough real />);
    ready();
    fireEvent.focus(screen.getByRole("button", { name: "Next" }));
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    next();
    fireEvent.click(screen.getByRole("button", { name: "Play walkthrough" }));
    fireEvent.focus(screen.getByRole("link", { name: "Find headphones" }));
    advance(30_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
  });

  it("keeps reduced-motion viewers in control and honors preference changes", () => {
    reduceMotion = true;
    render(<WorkspaceWalkthrough real />);
    ready();
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /walkthrough/ })).toBeNull();
    next();
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    reduceMotion = false;
    act(() => motionChange?.());
    fireEvent.click(screen.getByRole("button", { name: "Play walkthrough" }));
    reduceMotion = true;
    act(() => motionChange?.());
    advance(30_000);
    expect(screen.getByLabelText("Step 2 of 5")).toBeTruthy();
    next();
    next();
    next();
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    advance(30_000);
    expect(screen.getByLabelText("Step 1 of 5")).toBeTruthy();
  });

  it("keeps the need order and sends each action to its real catalog search", () => {
    render(<WorkspaceWalkthrough real />);
    const categories = ["headphones", "chair", "monitor"];
    for (const [index, story] of editorialStories.entries()) {
      next();
      const url = new URL(screen.getByRole("link").getAttribute("href")!, "http://localhost");
      expect(url.pathname).toBe("/catalog");
      expect(url.searchParams.get("q")).toBe(story.query);
      expect(url.searchParams.get("view")).toBe("results");
      expect(url.searchParams.get("category_key")).toBe(categories[index]);
    }
    next();
    const final = new URL(screen.getByRole("link").getAttribute("href")!, "http://localhost");
    expect(final.searchParams.get("q")).toBe(editorialStories[0].query);
    expect(final.searchParams.get("category_key")).toBe("headphones");
  });
});
