// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MosaicLabsPage } from "./MosaicLabsPage";

describe("MosaicLabsPage", () => {
  afterEach(cleanup);

  it("presents exactly three core labs and all eight participant runs", () => {
    const { container } = render(<MosaicLabsPage />);

    expect(screen.getByRole("heading", { name: "Mosaic Labs" })).toBeTruthy();
    expect(container.querySelectorAll(".labs-stage-card")).toHaveLength(3);
    expect(container.querySelectorAll(".labs-query-deck li")).toHaveLength(8);
    expect(screen.getByText("Retrieve", { selector: ".labs-stage-switcher strong" })).toBeTruthy();
    expect(screen.getByText("Rank", { selector: ".labs-stage-switcher strong" })).toBeTruthy();
    expect(screen.getByText("Reason", { selector: ".labs-stage-switcher strong" })).toBeTruthy();
  });

  it("keeps HNSW tuning in the optional advanced lane", () => {
    render(<MosaicLabsPage />);

    expect(screen.getByRole("heading", {
      name: "Tune the HNSW operating point with measured evidence.",
    })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Open advanced extension/ }).getAttribute("href"),
    ).toBe("/labs/performance");
  });
});
