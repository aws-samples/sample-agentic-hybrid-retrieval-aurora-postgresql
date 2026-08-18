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

  it("searches a hero prompt chip for exactly the words printed on it", () => {
    const { container } = renderPage();

    const chips = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".discover-hero-prompts > button"),
    );
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Best noise-cancelling headphones",
      "Ergonomic office chair",
      "Headphones for a long flight",
      "Sonora WH-C720",
      "Auraluxe H9",
      "Carbon-plated shoes",
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

  it("previews Mosaic Labs with product-led retrieval, ranking, and evidence scenes", () => {
    const { container } = renderPage();

    expect(
      screen.getByText(
        "Exact words, close spellings, and meaning, together over the live"
        + " catalog, with each starter's category filter already applied.",
      ),
    ).toBeTruthy();
    // Lab 2 dropped "explain"; the Labs page carries the same title.
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
