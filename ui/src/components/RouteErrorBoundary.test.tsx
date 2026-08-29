// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

function Exploding(): never {
  throw new Error("Failed to fetch dynamically imported module");
}

describe("RouteErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error itself, and the boundary logs the component
    // stack. Neither is a test failure.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders children when nothing throws", () => {
    render(
      <RouteErrorBoundary>
        <p>Discover</p>
      </RouteErrorBoundary>,
    );

    expect(screen.getByText("Discover")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a recoverable message instead of unmounting the tree", () => {
    // Every route is a lazy() chunk, so a dropped connection mid-navigation
    // rejects the import and React tears down the whole tree. Before this
    // boundary existed that left a blank document and a console-only error.
    render(
      <RouteErrorBoundary>
        <Exploding />
      </RouteErrorBoundary>,
    );

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("This surface did not load.");
    expect(alert.textContent).toContain("Failed to fetch dynamically imported module");
    expect(screen.getByRole("button", { name: "Reload Mosaic" })).toBeTruthy();
  });

  it("clears a failed surface when navigation changes its reset key", async () => {
    const view = render(
      <RouteErrorBoundary resetKey="/catalog">
        <Exploding />
      </RouteErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();

    view.rerender(
      <RouteErrorBoundary resetKey="/search">
        <p>Search surface</p>
      </RouteErrorBoundary>,
    );

    expect(await screen.findByText("Search surface")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
