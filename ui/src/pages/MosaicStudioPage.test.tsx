// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MosaicStudioPage } from "./MosaicStudioPage";

describe("MosaicStudioPage", () => {
  beforeAll(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    cleanup();
  });

  it("renders curated catalog fixtures immediately without a retrieval request", () => {
    render(<MosaicStudioPage />);

    expect(screen.getByRole("link", { name: "Explore" }).getAttribute("href")).toBe(
      "/mosaic-labs",
    );
    expect(screen.getByRole("link", { name: "Studio" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(
      screen.getByRole("link", { name: "HNSW at scale" }).getAttribute("href"),
    ).toBe("/mosaic-labs/hnsw");
    expect(screen.getByRole("heading", { name: "Compose a creative workspace." })).toBeTruthy();
    expect(document.querySelector(".labs-intro")?.classList).toContain(
      "labs-intro--animated",
    );
    expect(document.querySelector(".labs-intro-flow[aria-hidden=true] canvas")).toBeTruthy();
    expect(
      screen.getByText(/The language below is a creative brief, not an executed search/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Assemble the studio" })).toBeTruthy();
    expect(screen.getByText("Three curated sets ready")).toBeTruthy();
    expect(screen.queryByText(/Retrieving studio candidates/)).toBeNull();
  });

  it("changes fixture briefs and rotates the visible catalog piece", () => {
    render(<MosaicStudioPage />);

    fireEvent.click(screen.getByRole("button", { name: "Assemble the studio" }));
    expect(screen.getByRole("link", { name: /Forma Ergonomic/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Atelier 32/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Keysmith MX Quiet/ })).toBeTruthy();
    expect(screen.getAllByText("Curated piece 1 of 3")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Try another Focus seating" }));
    expect(screen.getByRole("link", { name: /PostureWorks Pro Mesh/ })).toBeTruthy();
    expect(screen.getByText("Curated piece 2 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Shared studio" }));
    expect(screen.getByRole("button", { name: "Assemble the studio" })).toBeTruthy();
    expect(screen.getByText("A calm setup for shared creative work.")).toBeTruthy();
    expect(
      screen.getByText("quiet wireless input for a shared creative workspace"),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Shop the workspace" })).toBeNull();
  });

  it("starts and stops the optional studio tour without waiting for retrieval", () => {
    render(<MosaicStudioPage />);

    fireEvent.click(screen.getByRole("button", { name: "Play studio tour" }));
    expect(screen.getByRole("button", { name: "Stop studio tour" })).toBeTruthy();
    expect(screen.getByText("Studio assembled")).toBeTruthy();
    expect(document.querySelector(".discover-studio-canvas")?.getAttribute("aria-live")).toBe(
      "off",
    );

    fireEvent.click(screen.getByRole("button", { name: "Stop studio tour" }));
    expect(screen.getByRole("button", { name: "Play studio tour" })).toBeTruthy();
  });

  it("does not offer an auto-rotating tour when reduced motion is requested", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    render(<MosaicStudioPage />);

    expect(screen.queryByRole("button", { name: "Play studio tour" })).toBeNull();
    expect(screen.getByRole("button", { name: "Assemble the studio" })).toBeTruthy();
  });
});
