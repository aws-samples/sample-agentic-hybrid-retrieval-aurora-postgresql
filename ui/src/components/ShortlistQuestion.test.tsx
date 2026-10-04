// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShortlistQuestion } from "./ShortlistQuestion";

const LONG = "I am finishing my home office. Check the Logitech Zone 900 for noise cancellation and the ViewSonic monitor for a 27-inch 4K screen.";

/** jsdom has no layout, so a clamped line is simulated by its scroll height. */
function overflowBy(scrollHeight: number, clientHeight: number) {
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(scrollHeight);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(clientHeight);
}

describe("ShortlistQuestion", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("offers Show all only when the question overflows two lines, and toggles it", () => {
    overflowBy(80, 52);
    render(<ShortlistQuestion question={LONG} />);

    const toggle = screen.getByRole("button", { name: "Show all" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText(LONG).className).toContain("is-clamped");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(LONG).className).not.toContain("is-clamped");
  });

  it("has no toggle for a question that fits", () => {
    overflowBy(52, 52);
    render(<ShortlistQuestion question="Which chair?" />);
    expect(screen.queryByRole("button", { name: /Show/ })).toBeNull();
  });

  it("renders nothing without a question", () => {
    const { container } = render(<ShortlistQuestion question="" />);
    expect(container.firstChild).toBeNull();
  });
});
