// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { coreMosaicLabs, retrievalExampleHref } from "../labMissions";
import { RETRIEVAL_SURFACE } from "../navigation";
import { DiscoverPage } from "./DiscoverPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
    suggestions: vi.fn(),
  },
}));

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.suggestions).mockReset();
    vi.mocked(api.suggestions).mockResolvedValue({
      query: "sono",
      suggestions: [
        {
          kind: "product",
          label: "Sonora WH-C720 Wireless Noise-Cancelling Headphones",
          query: "Sonora WH-C720 Wireless Noise-Cancelling Headphones",
          product_id: 2,
          domain: "consumer_electronics",
          brand: "Sonora",
          category_key: "over-ear-headphones",
          category_path: "Audio > Over-Ear Headphones",
        },
      ],
    });
  });

  afterEach(cleanup);

  function renderPage() {
    return render(
      <CommerceProvider>
        <DiscoverPage />
      </CommerceProvider>,
    );
  }

  it("routes a typed product need into Shop retrieval", () => {
    const { container } = renderPage();

    fireEvent.change(screen.getByRole("combobox", { name: "Search products" }), {
      target: { value: "quiet keyboard under $180" },
    });
    expect(
      container.querySelector(".discover-search .generative-search-icon"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(window.location.pathname).toBe("/catalog");
    expect(new URLSearchParams(window.location.search).get("q")).toBe(
      "quiet keyboard under $180",
    );
  });

  it("puts the only search field in the hero, with no scroll-to-search step", () => {
    const { container } = renderPage();

    expect(
      container.querySelectorAll("input[role='combobox']"),
    ).toHaveLength(1);
    expect(
      container.querySelector(".discover-hero .discover-search input"),
    ).toBe(screen.getByRole("combobox", { name: "Search products" }));
    expect(screen.queryByRole("button", { name: "Search the catalog" })).toBeNull();
    expect(screen.queryByText("Explore collections")).toBeNull();
  });

  it("keeps three search-aligned hero prompts and searches the printed words", () => {
    const { container } = renderPage();

    const chips = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".discover-hero-prompts > button"),
    );
    expect(container.querySelector(".discover-hero-prompts > span")?.textContent).toBe(
      "Try a search",
    );
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Best noise-cancelling headphones",
      "Ergonomic office chair",
      "Headphones for a long flight",
    ]);

    fireEvent.click(chips[0]);

    expect(window.location.pathname).toBe("/catalog");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("Best noise-cancelling headphones");
    expect(params.get("category_key")).toBe("over-ear-headphones");
  });

  it("links every category tile to a real filtered catalog route", () => {
    const { container } = renderPage();

    const tiles = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".discover-intention-tile"),
    );
    expect(tiles).toHaveLength(6);
    expect(tiles[0].getAttribute("href")).toBe(
      "/catalog?domain=consumer_electronics&category_key=over-ear-headphones",
    );
    // No product counts: Discover never requests the facets that would back them.
    expect(
      container.querySelector(".discover-intention-rail")?.textContent,
    ).not.toMatch(/\d/);
  });

  it("keeps editorial search free of a typeahead overlay", async () => {
    renderPage();
    const input = screen.getByRole("combobox", { name: "Search products" });

    fireEvent.change(input, { target: { value: "sono" } });
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => {
      expect(api.suggestions).toHaveBeenCalledWith(
        "sono",
        expect.any(AbortSignal),
      );
    });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders the editorial Shop preview immediately without a catalog request", () => {
    renderPage();

    // One shopping section, not two. The category tiles used to carry their own
    // "Shop with intention" heading directly above this one.
    expect(screen.getByRole("heading", { name: "Shop with intention" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: /Shop with intention/ })).toHaveLength(1);
    expect(screen.getByText("Browse a category with its filter already set.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Auraluxe H9" })).toBeTruthy();
    expect(screen.getByText("4.8")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Shop all" }).getAttribute("href")).toBe("/catalog");
    expect(vi.mocked(api.catalog)).not.toHaveBeenCalled();
  });

  it("previews the Observatory with product-led retrieval, ranking, and evidence scenes", () => {
    const { container } = renderPage();

    expect(
      screen.getByText(
        "Exact words, close spellings, and meaning, together over the live"
        + " catalog, with each starter's category filter already applied.",
      ),
    ).toBeTruthy();
    // Lab 2 dropped "explain"; the Observatory carries the same title.
    expect(screen.getByText("Fuse, rerank, and inspect")).toBeTruthy();
    expect(
      screen.getByText(
        "See how Mosaic retrieves candidates, ranks results, and grounds recommendations.",
      ),
    ).toBeTruthy();
    expect(container.querySelectorAll(".discover-lab-scene")).toHaveLength(3);
    expect(container.querySelectorAll(".discover-lab-candidate")).toHaveLength(2);
    expect(container.querySelectorAll(".discover-lab-rank-product")).toHaveLength(3);
    expect(container.querySelector(".discover-lab-evidence")).toBeTruthy();
    expect(container.querySelector(".discover-lab-svg")).toBeNull();
    expect(container.querySelectorAll(".discover-lab-graphic")).toHaveLength(3);
    expect(container.querySelectorAll(".discover-lab-copy")).toHaveLength(3);
  });

  it("names the surface it links to, with the one name for it", () => {
    // The band's kicker read "Mosaic Labs" while its own button read "Open
    // Retrieval Observatory" and its links went to /labs/retrieval. Three names for
    // one destination, two of them on one screen.
    //
    // The name comes from RETRIEVAL_SURFACE, which the header and the Labs tab
    // strip also read, so renaming the surface cannot leave this page behind.
    const { container } = renderPage();
    const band = container.querySelector(".discover-labs")!;

    expect(band.querySelector(".discover-labs-kicker")?.textContent).toBe(
      RETRIEVAL_SURFACE.label,
    );
    expect(band.textContent).not.toContain("Mosaic Labs");
    expect(
      band.querySelector<HTMLAnchorElement>(".discover-labs-cta")?.getAttribute("href"),
    ).toBe(RETRIEVAL_SURFACE.path);
  });

  it("links the three required labs to their real inspection surfaces", () => {
    const { container } = renderPage();
    const scenarios = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".discover-labs-scenario"),
    );

    expect(scenarios).toHaveLength(coreMosaicLabs.length);
    expect(scenarios.map((scenario) => scenario.getAttribute("href"))).toEqual(
      coreMosaicLabs.map(retrievalExampleHref),
    );
    expect(screen.getByText("Candidate recall across retrievers")).toBeTruthy();
    expect(screen.getByText("RRF ranking before rerank")).toBeTruthy();
    expect(screen.getByText("Evidence-backed agent answer")).toBeTruthy();
    expect(screen.queryByText("Exact identity with FTS")).toBeNull();
    expect(screen.queryByText("Tune the HNSW operating point")).toBeNull();
    expect(screen.getAllByText("Before / after")).toHaveLength(3);
  });

  it("runs a natural-language starter with its intentional category constraint", () => {
    renderPage();

    const starter = "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.";
    fireEvent.click(screen.getByRole("button", { name: starter }));

    expect(window.location.pathname).toBe("/catalog");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe(starter);
    expect(params.get("domain")).toBe("home_office");
    expect(params.get("category_key")).toBe("ergonomic-office-chairs");
  });

});
