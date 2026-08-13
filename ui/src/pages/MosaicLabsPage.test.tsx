// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { showcaseProductDetail } from "../showcase";
import { MosaicLabsPage } from "./MosaicLabsPage";

vi.mock("../api", () => ({
  api: {
    product: vi.fn(),
  },
}));

const engineProductIds = [2, 3, 4, 5, 1, 17001];

describe("MosaicLabsPage", () => {
  beforeAll(() => {
    // jsdom ships no canvas backend and logs "Not implemented" for every
    // getContext call the masthead field makes. LabsIntroFlow already reads a
    // null context as "do not animate", the same branch a reduced-motion
    // machine takes, so returning null exercises real code and keeps the suite
    // output clean instead of pulling in a native canvas dependency.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });
  beforeEach(() => {
    vi.mocked(api.product).mockReset();
    vi.mocked(api.product).mockImplementation((productId) => {
      const product = showcaseProductDetail(productId);
      if (!product) return Promise.reject(new Error(`Missing test product ${productId}`));
      return Promise.resolve(product);
    });
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("presents the three labs as read-only observation with Shop proof scenarios", async () => {
    const { container } = render(<MosaicLabsPage />);

    expect(screen.getByRole("heading", {
      name: "Explore. Ask. Understand.",
    })).toBeTruthy();
    expect(
      screen.getByText("Build the retrieval system first. Then give it to the agent."),
    ).toBeTruthy();
    expect(container.querySelectorAll(".labs-stage-card")).toHaveLength(3);
    expect(
      screen.getByText(
        "Workshop Studio owns the broken snippet, hint, and repair. Mosaic Labs explains the system state; Shop is the customer-facing proof.",
      ),
    ).toBeTruthy();
    expect(container.querySelectorAll(".labs-shop-proofs a")).toHaveLength(8);
    expect(
      [...container.querySelectorAll(".labs-shop-proofs")].map(
        (presets) => presets.querySelectorAll("a").length,
      ),
    ).toEqual([3, 3, 2]);
    expect(container.querySelectorAll(".labs-engine-rail > li")).toHaveLength(6);
    expect(await screen.findByText("Live premium catalog records")).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(engineProductIds.length);
    // The masthead field is decoration, so it carries no text and no figure a
    // presenter could read a number off, and it stays out of the a11y tree.
    expect(container.querySelector(".labs-intro-flow[aria-hidden=true] canvas")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Replay the path" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "One request, three retrieval outcomes." }),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("link", { name: "Inspect FTS, vector, and hybrid" }),
    ).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: /View Lab 1 in Shop/ }).getAttribute("href"),
    ).toMatch(/^\/catalog\?/);
    expect(
      screen.getAllByRole("link", { name: /Open Shop scenario/ })[2].getAttribute("href"),
    ).toMatch(/^\/catalog\?/);
    expect(screen.queryByText(/Restore the trigram CTE/)).toBeNull();
  });

  it("replays the visible path from query parsing through grounded evidence", async () => {
    vi.useFakeTimers();
    try {
      render(<MosaicLabsPage />);

      const replay = screen.getByRole("button", { name: "Replay the path" });
      fireEvent.click(replay);

      expect((replay as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText("Parse one request before searching")).toBeTruthy();

      act(() => {
        vi.advanceTimersByTime(620 * 5);
      });

      expect(screen.getByText("Ground the recommendation in evidence")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Replay the path" })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps HNSW tuning in the optional advanced lane", async () => {
    render(<MosaicLabsPage />);

    expect(screen.getByText("Advanced observability")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Open HNSW diagnostics/ }).getAttribute("href"),
    ).toBe("/labs/performance");
    expect(screen.getAllByText("hnsw.ef_search")).toHaveLength(2);
  });

  it("does not substitute a mock cohort when catalog records cannot load", async () => {
    vi.mocked(api.product).mockRejectedValue(new Error("Aurora is unavailable"));
    const { container } = render(<MosaicLabsPage />);

    expect(
      await screen.findByText(
        "Catalog product records are unavailable: Aurora is unavailable",
      ),
    ).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(0);
  });
});
