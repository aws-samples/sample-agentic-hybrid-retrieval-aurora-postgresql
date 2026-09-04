// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunSummary, shortEventId } from "./RunSummary";

const BASELINE_ID = "9f92f8cc-efc2-4d81-a94a-69638d050282";
const LATEST_ID = "9614ed9b-4ceb-4aad-9276-4e69af2231b9";

afterEach(cleanup);

describe("RunSummary", () => {
  it("names the run on screen and the run it is measured against", () => {
    render(
      <RunSummary
        baselineSearchEventId={BASELINE_ID}
        latestSearchEventId={LATEST_ID}
        onPinBaseline={vi.fn()}
      />,
    );

    const summary = document.querySelector(".labs-run-summary");
    expect(summary?.textContent).toContain(`Run on screen ${shortEventId(LATEST_ID)}`);
    expect(summary?.textContent).toContain(`Baseline ${shortEventId(BASELINE_ID)}`);
    // Recognisable, not 36 characters of UUID on a projector.
    expect(summary?.textContent).not.toContain(LATEST_ID);
  });

  it("renders nothing before there is a run to report", () => {
    const { container } = render(
      <RunSummary
        baselineSearchEventId={null}
        latestSearchEventId={null}
        onPinBaseline={vi.fn()}
      />,
    );

    expect(container.innerHTML).toBe("");
  });

  it("says so when no baseline is pinned yet", () => {
    render(
      <RunSummary
        baselineSearchEventId={null}
        latestSearchEventId={LATEST_ID}
        onPinBaseline={vi.fn()}
      />,
    );

    expect(screen.getByText("No baseline pinned")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pin as baseline" }).hasAttribute("disabled"))
      .toBe(false);
  });

  it("pins the run on screen when asked", () => {
    const onPinBaseline = vi.fn();
    render(
      <RunSummary
        baselineSearchEventId={BASELINE_ID}
        latestSearchEventId={LATEST_ID}
        onPinBaseline={onPinBaseline}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Pin as baseline" }));

    expect(onPinBaseline).toHaveBeenCalledTimes(1);
  });

  it("offers no way to pin the run that is already the baseline", () => {
    // Every carried arrival lands here: the Shop run is both the run on screen
    // and the pinned baseline, and re-pinning it changes nothing.
    render(
      <RunSummary
        baselineSearchEventId={LATEST_ID}
        latestSearchEventId={LATEST_ID}
        onPinBaseline={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Pin as baseline" }).hasAttribute("disabled"))
      .toBe(true);
  });
});
