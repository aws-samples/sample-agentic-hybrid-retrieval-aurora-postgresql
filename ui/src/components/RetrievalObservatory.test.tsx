// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { showcaseProductDetail } from "../showcase";
import { RetrievalObservatory } from "./RetrievalObservatory";

vi.mock("../api", () => ({
  api: {
    product: vi.fn(),
  },
}));

const engineProductIds = [2, 3, 4, 5, 1, 17001];

describe("RetrievalObservatory", () => {
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

  it("holds the product cohort until the participant replays the fixture", async () => {
    const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "From request to grounded output." })).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-rail > li")).toHaveLength(6);
    expect(
      container.querySelector(".labs-engine-rail button[aria-current=step] strong")?.textContent,
    ).toBe("Query");
    expect(screen.getByText("Awaiting fixture replay.")).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(0);
    expect(
      container.querySelector<HTMLButtonElement>(".labs-engine-rail button")?.disabled,
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Replay fixture" }));

    expect(await screen.findByText("Canonical catalog fixture")).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(engineProductIds.length);
  });

  it("keeps the illustrated product cards mounted while a selected stage changes their state", async () => {
    const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);
    const echoBudFigure = () => (
      [...container.querySelectorAll<HTMLElement>(".labs-engine-product")].find(
        (figure) => figure.querySelector("figcaption strong")?.textContent === "EchoBud S2",
      )
    );

    fireEvent.click(screen.getByRole("button", { name: "Replay fixture" }));
    await waitFor(() => expect(echoBudFigure()).toBeTruthy());
    const initialFigure = echoBudFigure();
    fireEvent.click(container.querySelectorAll<HTMLButtonElement>(".labs-engine-rail button")[5]);

    expect(echoBudFigure()).toBe(initialFigure);
    expect(within(initialFigure!).getByText("Evidence trace")).toBeTruthy();
  });

  it.each([
    {
      label: "Typo recovery",
      candidate: [2, 3, 4, 5, 1, 17001],
      fused: [2, 4, 3, 5],
      reranked: [2, 4, 3],
    },
    {
      label: "Semantic intent",
      candidate: [3, 5, 2, 4, 1, 17001],
      fused: [3, 2, 5, 4],
      reranked: [3, 5, 2],
    },
  ])("binds the $label replay ordering to its fixture", async ({ label, candidate, fused, reranked }) => {
    const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);
    const orderedVisibleProductIds = () => (
      [...container.querySelectorAll<HTMLElement>(".labs-engine-product")]
        .filter((figure) => !figure.classList.contains("muted"))
        .sort(
          (left, right) => (
            Number(left.style.getPropertyValue("--product-order"))
            - Number(right.style.getPropertyValue("--product-order"))
          ),
        )
        .map((figure) => Number(figure.dataset.productId))
    );
    const stageButtons = container.querySelectorAll<HTMLButtonElement>(".labs-engine-rail button");

    fireEvent.click(screen.getByRole("button", { name: new RegExp(`Use ${label} query:`) }));
    fireEvent.click(screen.getByRole("button", { name: "Replay fixture" }));
    await waitFor(() => {
      expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(engineProductIds.length);
    });
    if (label === "Typo recovery") {
      fireEvent.click(screen.getByRole("button", { name: "After repair" }));
    }
    fireEvent.click(stageButtons[1]);
    expect(orderedVisibleProductIds()).toEqual(candidate);

    fireEvent.click(stageButtons[3]);
    expect(orderedVisibleProductIds()).toEqual(fused);

    fireEvent.click(stageButtons[4]);
    expect(orderedVisibleProductIds()).toEqual(reranked);
  });

  it("makes typo recovery failure and repair visible before a participant runs the live trace", async () => {
    const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Use Typo recovery query:/ }));
    fireEvent.click(screen.getByRole("button", { name: "Replay fixture" }));
    await waitFor(() => {
      expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(engineProductIds.length);
    });
    fireEvent.click(container.querySelectorAll<HTMLButtonElement>(".labs-engine-rail button")[1]);

    expect(screen.getByText(/^Before repair: .* is not recovered\.$/)).toBeTruthy();
    expect(screen.getByText("Target absent")).toBeTruthy();
    expect(screen.getByText("pg_trgm pool: 0")).toBeTruthy();
    expect(screen.getByText("No trigram contribution")).toBeTruthy();
    expect(
      container.querySelector('[data-product-id="2"]')?.classList.contains("target-missed"),
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "After repair" }));

    expect(screen.getByText(/^After repair: .* is recovered\.$/)).toBeTruthy();
    expect(screen.getByText("Target returned")).toBeTruthy();
    expect(screen.getByText("pg_trgm rank present")).toBeTruthy();
    expect(screen.getByText("RRF contribution present")).toBeTruthy();
  });

  it("selects the corresponding live lab example from the illustrated trace", () => {
    const onSelectExample = vi.fn();
    render(<RetrievalObservatory onSelectExample={onSelectExample} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Inspect live trace" })[0]);

    expect(onSelectExample).toHaveBeenCalledWith("exact-identity");
  });

  it("replays the visible path from query parsing through grounded evidence", async () => {
    vi.useFakeTimers();
    try {
      const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);
      const replay = screen.getByRole("button", { name: "Replay fixture" });
      fireEvent.click(replay);

      expect((replay as HTMLButtonElement).disabled).toBe(true);
      expect(replay.textContent).toContain("Replaying 1 of 6");
      expect(container.querySelector(".labs-engine-board.is-replaying")).toBeTruthy();

      act(() => {
        vi.runAllTimers();
      });

      expect(screen.getByText("Ground the recommendation in evidence")).toBeTruthy();
      expect(container.querySelector(".labs-engine-board.is-replaying")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not substitute a mock cohort when catalog records cannot load", async () => {
    vi.mocked(api.product).mockRejectedValue(new Error("Aurora is unavailable"));
    const { container } = render(<RetrievalObservatory onSelectExample={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Replay fixture" }));

    expect(
      await screen.findByText("Catalog product records are unavailable: Aurora is unavailable"),
    ).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(0);
  });
});
