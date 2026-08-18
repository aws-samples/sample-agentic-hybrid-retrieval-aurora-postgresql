// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs, supportingMosaicChecks } from "../labMissions";
import { showcaseProductDetail } from "../showcase";
import { labAnchorId, labScenarioTargets, MosaicLabsPage } from "./MosaicLabsPage";

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

  it("pictures whichever product each lens's own Shop scenarios run against most", () => {
    // The frame is captioned "Product anchor", so it asserts a relationship to
    // the scenarios listed beside it. Choosing the photograph by hand broke that:
    // the reason lens pictured a keyboard while both of its scenarios ask about
    // an ergonomic chair.
    for (const lab of coreMosaicLabs) {
      const targets = labScenarioTargets(lab);
      const anchor = labAnchorId(lab);
      expect(targets).toContain(anchor);

      const uses = (id: number) => targets.filter((target) => target === id).length;
      for (const target of targets) {
        expect(uses(anchor)).toBeGreaterThanOrEqual(uses(target));
      }
    }

    // One distinct product per lens, and the reason lens lands on its chair.
    const anchors = coreMosaicLabs.map(labAnchorId);
    expect(new Set(anchors).size).toBe(anchors.length);
    expect(anchors).toEqual([2, 370002, 370001]);
  });

  it("presents the three system lenses as read-only observation with Shop scenarios", async () => {
    const { container } = render(<MosaicLabsPage />);

    expect(screen.getByRole("heading", {
      name: "Retrieval observatory. Grounded answers.",
    })).toBeTruthy();
    expect(
      screen.getByText(
        "Follow a real request as it moves from intent to an evidence-backed recommendation.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Explore" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("link", { name: "Studio" }).getAttribute("href")).toBe(
      "/mosaic-labs/studio",
    );
    expect(
      screen.getByRole("link", { name: "HNSW at scale" }).getAttribute("href"),
    ).toBe("/mosaic-labs/hnsw");
    expect(screen.getByText("Optional read-only views.")).toBeTruthy();
    const sourceLink = screen.getByRole("link", {
      name: "View Mosaic source on GitHub (opens in a new tab)",
    });
    expect(sourceLink.getAttribute("href")).toBe(
      "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql",
    );
    expect(sourceLink.getAttribute("target")).toBe("_blank");
    expect(sourceLink.getAttribute("rel")).toBe("noreferrer");
    expect(sourceLink.querySelector("img")?.getAttribute("src")).toBe(
      "/assets/icons/github-mark.svg",
    );
    expect(container.querySelectorAll(".labs-stage-card")).toHaveLength(3);
    expect(
      screen.getByText(
        "Author the repair in Code Editor. Validate its customer-visible effect in Shop. Return here only to inspect the system evidence.",
      ),
    ).toBeTruthy();
    expect(container.querySelectorAll(".labs-scenario-menu a")).toHaveLength(8);
    expect(
      [...container.querySelectorAll(".labs-scenario-menu")].map(
        (presets) => presets.querySelectorAll("a").length,
      ),
    ).toEqual([3, 3, 2]);
    expect(
      [...container.querySelectorAll<HTMLDetailsElement>(".labs-scenario-menu")].every(
        (menu) => !menu.open,
      ),
    ).toBe(true);
    expect(container.querySelectorAll(".labs-engine-rail > li")).toHaveLength(6);
    expect(
      container.querySelector(".labs-engine-rail button[aria-current=step] strong")?.textContent,
    ).toBe("Query");
    expect(await screen.findByText("Canonical catalog fixture")).toBeTruthy();
    expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(engineProductIds.length);
    expect(container.querySelector(".labs-intro")?.classList).toContain(
      "labs-intro--compact",
    );
    expect(container.querySelector(".labs-intro-flow")).toBeNull();
    expect(screen.queryByText("System replay")).toBeNull();
    expect(screen.queryByText("Observation gallery")).toBeNull();
    expect(screen.getByRole("button", { name: "Replay fixture" })).toBeTruthy();
    const queryExamples = screen.getByRole("group", { name: "Replay query examples" });
    expect(queryExamples.querySelectorAll("button")).toHaveLength(3);
    expect(
      [...queryExamples.querySelectorAll("button")].map((button) => button.textContent),
    ).toEqual(["Exact identity", "Typo recovery", "Semantic intent"]);
    const exactIdentity = supportingMosaicChecks.find(
      (check) => check.id === "exact-identity",
    );
    if (!exactIdentity) throw new Error("Missing exact-identity fixture");
    expect(
      container.querySelector(".labs-engine-query code")?.getAttribute("aria-label"),
    ).toBe(exactIdentity.query);
    expect(
      screen.getByRole("heading", { name: "Where one retrieval method stops being enough." }),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("link", { name: "Inspect the trace" }),
    ).toHaveLength(3);
    expect(
      screen.getByRole("link", { name: "Open a Shop scenario" }).getAttribute("href"),
    ).toMatch(/^\/catalog\?/);
    expect(
      screen.getAllByRole("link", { name: "Open in Shop" })[2].getAttribute("href"),
    ).toMatch(/^\/catalog\?/);
    expect(screen.queryByText(/Restore the trigram CTE/)).toBeNull();
  });

  it("routes advanced HNSW diagnostics into the canonical Labs view", () => {
    render(<MosaicLabsPage />);

    expect(
      screen.getByRole("link", { name: "Open HNSW at scale" }).getAttribute("href"),
    ).toBe("/mosaic-labs/hnsw");
  });

  it("types each canonical replay query before emphasizing the replay control", () => {
    vi.useFakeTimers();
    const semanticIntent = supportingMosaicChecks.find(
      (check) => check.id === "semantic-intent-contrast",
    );
    const exactIdentity = supportingMosaicChecks.find(
      (check) => check.id === "exact-identity",
    );
    if (!semanticIntent) throw new Error("Missing semantic-intent-contrast fixture");
    if (!exactIdentity) throw new Error("Missing exact-identity fixture");

    const { container } = render(<MosaicLabsPage />);
    const typedQuery = container.querySelector(".labs-engine-query-typed");
    const replay = screen.getByRole("button", { name: "Replay fixture" });

    expect(typedQuery?.textContent).toBe("");
    expect(replay.classList.contains("query-ready")).toBe(false);

    act(() => {
      vi.advanceTimersByTime(exactIdentity.query.length * 50);
    });
    expect(typedQuery?.textContent).toBe(exactIdentity.query);
    expect(replay.classList.contains("query-ready")).toBe(true);

    fireEvent.click(
      screen.getByRole("button", { name: /Use Semantic intent query:/ }),
    );
    expect(
      container.querySelector(".labs-engine-query code")?.getAttribute("aria-label"),
    ).toBe(semanticIntent.query);
    expect(typedQuery?.textContent).toBe("");
    expect(screen.getByText("Start with one request")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(semanticIntent.query.length * 50);
    });
    expect(typedQuery?.textContent).toBe(semanticIntent.query);
    expect(replay.classList.contains("query-ready")).toBe(true);
  });

  it("moves an exact identity into first place at retrieval and explains why it stays there", async () => {
    const { container } = render(<MosaicLabsPage />);

    const echoBudFigure = () => (
      [...container.querySelectorAll<HTMLElement>(".labs-engine-product")].find(
        (figure) => figure.querySelector("figcaption strong")?.textContent === "EchoBud S2",
      )
    );
    const stageButtons = container.querySelectorAll<HTMLButtonElement>(
      ".labs-engine-rail button",
    );

    await waitFor(() => expect(echoBudFigure()).toBeTruthy());
    expect(echoBudFigure()?.style.getPropertyValue("--product-order")).toBe("6");

    fireEvent.click(stageButtons[1]);
    expect(echoBudFigure()?.style.getPropertyValue("--product-order")).toBe("1");
    expect(screen.getAllByText("Exact FTS identity").length).toBeGreaterThan(0);

    fireEvent.click(stageButtons[4]);
    expect(echoBudFigure()?.style.getPropertyValue("--product-order")).toBe("1");
    expect(screen.getAllByText("Exact model remains #1").length).toBeGreaterThan(0);
  });

  it("keeps product cards mounted while replay labels and emphasis change", async () => {
    const { container } = render(<MosaicLabsPage />);
    const echoBudFigure = () => (
      [...container.querySelectorAll<HTMLElement>(".labs-engine-product")].find(
        (figure) => figure.querySelector("figcaption strong")?.textContent === "EchoBud S2",
      )
    );
    const stageButtons = container.querySelectorAll<HTMLButtonElement>(
      ".labs-engine-rail button",
    );

    await waitFor(() => expect(echoBudFigure()).toBeTruthy());
    const initialFigure = echoBudFigure();
    fireEvent.click(stageButtons[5]);

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
  ])("keeps the $label replay ordering bound to its fixture", async ({
    label,
    candidate,
    fused,
    reranked,
  }) => {
    const { container } = render(<MosaicLabsPage />);
    await waitFor(() => {
      expect(container.querySelectorAll(".labs-engine-product")).toHaveLength(
        engineProductIds.length,
      );
    });

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
    const stageButtons = container.querySelectorAll<HTMLButtonElement>(
      ".labs-engine-rail button",
    );

    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`Use ${label} query:`) }),
    );
    fireEvent.click(stageButtons[1]);
    expect(orderedVisibleProductIds()).toEqual(candidate);

    fireEvent.click(stageButtons[3]);
    expect(orderedVisibleProductIds()).toEqual(fused);

    fireEvent.click(stageButtons[4]);
    expect(orderedVisibleProductIds()).toEqual(reranked);
  });

  it("replays the visible path from query parsing through grounded evidence", async () => {
    vi.useFakeTimers();
    try {
      const { container } = render(<MosaicLabsPage />);

      const replay = screen.getByRole("button", { name: "Replay fixture" });
      fireEvent.click(replay);

      expect((replay as HTMLButtonElement).disabled).toBe(true);
      expect(replay.textContent).toContain("Replaying 1 of 6");
      expect(container.querySelector(".labs-engine-board.is-replaying")).toBeTruthy();
      expect(screen.getByText("Start with one request")).toBeTruthy();

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByText("Start with one request")).toBeTruthy();

      act(() => {
        vi.advanceTimersByTime(650);
      });
      expect(screen.getByText("Build a candidate universe")).toBeTruthy();

      act(() => {
        vi.runAllTimers();
      });

      expect(screen.getByText("Ground the recommendation in evidence")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Replay fixture" })).toBeTruthy();
      expect(container.querySelector(".labs-engine-board.is-replaying")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps HNSW tuning in the optional advanced lane", async () => {
    const { container } = render(<MosaicLabsPage />);

    expect(screen.getByText("Advanced diagnostics")).toBeTruthy();
    expect(container.querySelector<HTMLDetailsElement>(".labs-advanced")?.open).toBe(false);
    expect(
      screen.getByRole("link", { name: /Open HNSW at scale/ }).getAttribute("href"),
    ).toBe("/mosaic-labs/hnsw");
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
