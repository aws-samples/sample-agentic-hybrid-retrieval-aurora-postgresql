// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
    expect(new URLSearchParams(window.location.search).get("view")).toBe("results");
  });

  it("puts the only search field in the hero, with no scroll-to-search step", () => {
    const { container } = renderPage();

    expect(
      container.querySelectorAll("input[role='combobox']"),
    ).toHaveLength(1);
    expect(
      container.querySelector(".discover-hero .discover-search input"),
    ).toBe(screen.getByRole("combobox", { name: "Search products" }));
    const submit = screen.getByRole("button", { name: "Search" });
    expect(submit.textContent).toBe("");
    expect(submit.querySelector("svg")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ask Mosaic" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Search the catalog" })).toBeNull();
    expect(screen.queryByText("Explore collections")).toBeNull();
  });

  it("keeps five curated hero prompts and searches exactly the printed words", () => {
    const { container } = renderPage();

    const chips = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".discover-hero-prompts > button"),
    );
    expect(container.querySelector(".discover-hero-prompts > span")?.textContent).toBe(
      "Try a search",
    );
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Focus headphones",
      "A chair for long workdays",
      "Travel-ready audio",
      "Quiet home office",
      "Recovery essentials",
    ]);

    fireEvent.click(chips[0]);

    // The label is the query, verbatim, and the category it browses travels with
    // it. Unconstrained, "Focus headphones" retrieved twelve products from
    // `acoustic-headphones` — three synthetic brands are named FocusErgonomics,
    // FocusOffice and FocusSystems — and that category owns no photography, so
    // Shop drew the same domain-neutral plate twelve times.
    expect(window.location.pathname).toBe("/catalog");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("Focus headphones");
    expect(params.get("view")).toBe("results");
    expect(params.get("category_key")).toBe("over-ear-headphones");
    expect(params.get("domain")).toBe("consumer_electronics");
  });

  it("never prints a misspelled query in Mosaic's own voice", () => {
    // The Lab 1 canonical query is deliberately misspelled and it is the
    // shopper's to type. Discover used to print it verbatim on a scenario card,
    // so the storefront shipped "wirless" and "hedphones" as its own copy.
    const { container } = renderPage();
    const text = container.textContent ?? "";

    for (const word of ["wirless", "noice", "hedphones", "batery", "fligts"]) {
      expect(text).not.toContain(word);
    }
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

  it("opens with an invitation rather than a product model", () => {
    // The headline promises "Search naturally" and the field then cycled through
    // "Sonora WH-C720" and "Mosaic Auraluxe H9" as ghost text, which reads as a
    // demo fixture. Cold start asks for the thing the hero just promised.
    const { container } = renderPage();
    const input = screen.getByRole("combobox", { name: "Search products" });

    expect((input as HTMLInputElement).value).toBe("");
    expect(input.getAttribute("placeholder")).toBe(
      "Describe what you're looking for...",
    );
    expect(container.querySelector(".catalog-idle-suggestion")).toBeNull();
    // Scoped to the hero. Auraluxe H9 is a real product and it belongs on a card in
    // the Shop preview below; what it must not be is ghost text in the search field.
    const hero = container.querySelector(".discover-hero")!;
    expect(hero.textContent).not.toContain("WH-C720");
    expect(hero.textContent).not.toContain("Auraluxe");
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

  it("previews the Playground with product-led retrieval, ranking, and evidence scenes", () => {
    const { container } = renderPage();

    expect(
      screen.getByRole("heading", {
        name: "Made for the way you work, move, and unwind.",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "See how Mosaic finds candidates, ranks them, and grounds every"
        + " recommendation it makes.",
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

  it("keeps implementation vocabulary off the storefront entirely", () => {
    // Discover is 80% commerce. FTS, pg_trgm, pgvector, HNSW and RRF are the
    // Playground's words, printed there beside the numbers that justify them.
    const { container } = renderPage();
    const text = container.textContent ?? "";

    for (const term of ["FTS", "pg_trgm", "pgvector", "HNSW", "RRF", "tsvector"]) {
      expect(text).not.toContain(term);
    }
    // The customer vocabulary is what the scene labels carry instead.
    expect(text).toContain("Exact terms");
    expect(text).toContain("Close spelling");
    expect(text).toContain("Meaning match");
  });

  it("names the surface it links to, with the one name for it", () => {
    // The band's kicker read "Mosaic Labs" while its own button read "Open
    // Retrieval Observatory" and its links went to /labs/retrieval. Three names for
    // one destination, two of them on one screen. The kicker is gone; the heading
    // carries its own weight and the call to action carries the name.
    const { container } = renderPage();
    const band = container.querySelector(".discover-labs")!;

    expect(band.querySelector(".discover-labs-kicker")).toBeNull();
    expect(band.textContent).not.toMatch(/Mosaic Labs|Observatory/);
    const cta = band.querySelector<HTMLAnchorElement>(".discover-labs-cta")!;
    expect(cta.getAttribute("href")).toBe(RETRIEVAL_SURFACE.path);
    expect(cta.textContent).toContain(RETRIEVAL_SURFACE.label);
  });

  it("links the three required labs to their real inspection surfaces", () => {
    // One card per lab, not two grids for three destinations. The stage cards all
    // pointed at the Playground root while a second row below them held the real
    // deep links, so six cards served three errands.
    const { container } = renderPage();
    const cards = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".discover-lab-card"),
    );

    expect(cards).toHaveLength(coreMosaicLabs.length);
    expect(cards.map((card) => card.getAttribute("href"))).toEqual(
      coreMosaicLabs.map(retrievalExampleHref),
    );
    expect(container.querySelector(".discover-labs-scenario")).toBeNull();
    // Editorial titles, not the missions' own `discover_label` values: two of the
    // three name the mechanism ("RRF ranking before rerank"), which belongs on the
    // Playground. The hrefs above are what proves the linkage is real.
    expect(
      cards.map((card) => card.querySelector(".discover-lab-copy strong")?.textContent),
    ).toEqual([
      "Three ways to find one product",
      "Watch the order change",
      "An answer that cites its sources",
    ]);
    expect(
      cards.map((card) => card.querySelector(".discover-lab-copy small")?.textContent),
    ).toEqual(["01 · Retrieve", "02 · Rank", "03 · Reason"]);
  });

  it("runs an editorial entry with its intentional category constraint", () => {
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
