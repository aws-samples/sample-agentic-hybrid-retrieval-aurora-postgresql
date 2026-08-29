// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CatalogSearchComposer } from "./CatalogSearchComposer";

vi.mock("../api", () => ({
  api: {
    suggestions: vi.fn(),
  },
}));

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("CatalogSearchComposer accessibility", () => {
  it.each([
    ["suggestions are hidden", { showSuggestions: false }],
    ["suggestions on type are disabled", { suggestionsOnType: false }],
  ])("uses plain search semantics when %s", (_label, props) => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    render(
      <CatalogSearchComposer
        {...props}
        onSubmit={vi.fn()}
      />,
    );

    const searchbox = screen.getByRole("searchbox");
    fireEvent.change(searchbox, {
      target: { value: "standing desk" },
    });
    fireEvent.keyDown(searchbox, { key: "ArrowDown" });
    act(() => vi.advanceTimersByTime(500));

    expect(api.suggestions).not.toHaveBeenCalled();
    expect(searchbox.hasAttribute("aria-autocomplete")).toBe(false);
    expect(searchbox.hasAttribute("aria-controls")).toBe(false);
    expect(searchbox.hasAttribute("aria-expanded")).toBe(false);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("does not fetch while the parent request is pending", () => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    render(
      <CatalogSearchComposer pending onSubmit={vi.fn()} />,
    );

    const combobox = screen.getByRole("combobox");
    fireEvent.change(combobox, {
      target: { value: "standing desk" },
    });
    fireEvent.keyDown(combobox, { key: "ArrowDown" });
    act(() => vi.advanceTimersByTime(500));

    expect(api.suggestions).not.toHaveBeenCalled();
    expect(combobox.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("pauses the rotating idle suggestion while the composer has focus", () => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    const view = render(
      <CatalogSearchComposer
        idleSuggestions={["first suggestion", "second suggestion"]}
        onSubmit={vi.fn()}
      />,
    );

    act(() => vi.advanceTimersByTime(1200));
    expect(view.container.querySelector(".catalog-idle-suggestion")?.textContent)
      .toBe("first suggestion");

    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    act(() => vi.advanceTimersByTime(10400));
    expect(view.container.querySelector(".catalog-idle-suggestion")?.textContent)
      .toBe("first suggestion");

    fireEvent.blur(input, { relatedTarget: null });
    act(() => vi.advanceTimersByTime(5200));
    expect(view.container.querySelector(".catalog-idle-suggestion")?.textContent)
      .toBe("second suggestion");
  });

  it("keeps one static idle suggestion under reduced motion", () => {
    vi.useFakeTimers();
    stubReducedMotion(true);
    const view = render(
      <CatalogSearchComposer
        idleSuggestions={["first suggestion", "second suggestion"]}
        onSubmit={vi.fn()}
      />,
    );

    expect(view.container.querySelector(".catalog-idle-suggestion")?.textContent)
      .toBe("first suggestion");
    act(() => vi.advanceTimersByTime(10400));
    expect(view.container.querySelector(".catalog-idle-suggestion")?.textContent)
      .toBe("first suggestion");
  });
});
