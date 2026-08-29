// @vitest-environment jsdom

import {
  act,
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
import type {
  CatalogPage,
  CatalogSummary,
  ProductSummary,
  ReviewHighlight,
  SearchFilters,
} from "../types";
import { DiscoverPage, editorialStories, merchandisingDoors } from "./DiscoverPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
    reviewHighlights: vi.fn(),
    suggestions: vi.fn(),
    summary: vi.fn(),
  },
}));

function countPage(total: number): CatalogPage {
  return { total, offset: 0, limit: 1, products: [], facets: {} };
}

// The full ProductSummary shape with the fields the pick rows read: id for the
// link, title, price and currency.
function pickFixture(id: number, filters: SearchFilters): ProductSummary {
  return {
    product_id: id,
    sku: `SKU-${id}`,
    title: `Top-rated ${filters.category_key}`,
    short_description: "",
    domain: "home_office",
    category_key: filters.category_key ?? "",
    category_path: "",
    brand: "Mosaic",
    model: `M-${id}`,
    price_cents: 24900,
    list_price_cents: 24900,
    currency: "USD",
    rating: 4.8,
    review_count: 240,
    availability: "in_stock",
    inventory_count: 12,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: false,
    is_retrieval_anchor: false,
    image_url: null,
    image_source: null,
    signals: null,
    sources: [],
  };
}

const summaryFixture: CatalogSummary = {
  total: {
    products: 500000,
    brands: 312,
    subcategories: 96,
    embedded_products: 500000,
    reviews: 128412,
    reviewed_products: 41250,
    average_rating: 4.6,
  },
  domains: [],
};

// Shaped like the live endpoint's verbatim excerpts: one opening sentence per
// highlight, each from a different product.
const voicesFixture: ReviewHighlight[] = [
  {
    review_id: 11112,
    product_id: 501,
    product_title: "Mosaic Atelier 32 Premium Workspace Display",
    brand: "Mosaic",
    rating: 5,
    quote:
      "Comfort held up through a full day and the build feels more durable than expected.",
    verified_purchase: true,
    review_date: "2026-03-14",
    source_uri: "mosaic://evidence/review/11112",
  },
  {
    review_id: 33,
    product_id: 502,
    product_title: "Mosaic Pulse One Health & Fitness Smartwatch",
    brand: "Mosaic",
    rating: 5,
    quote:
      "The performance-to-price balance is excellent, especially for the intended use case.",
    verified_purchase: true,
    review_date: "2026-01-02",
    source_uri: "mosaic://evidence/review/33",
  },
  {
    review_id: 6309,
    product_id: 503,
    product_title: "AeroStride Carbon Pro 3 Marathon Racing Shoes",
    brand: "AeroStride",
    rating: 4,
    quote:
      "I compared several alternatives and kept this one because the practical details were better.",
    verified_purchase: true,
    review_date: "2025-11-20",
    source_uri: "mosaic://evidence/review/6309",
  },
];

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.reviewHighlights).mockReset();
    vi.mocked(api.summary).mockReset();
    vi.mocked(api.suggestions).mockReset();
    // The merchandising band and the voices strip fetch on mount in every
    // test. Leaving the reads pending keeps the synchronous tests act()-clean;
    // the band tests override these with real resolutions.
    vi.mocked(api.catalog).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.reviewHighlights).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.summary).mockReturnValue(new Promise(() => {}));
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

    fireEvent.change(screen.getByRole("searchbox", { name: "Search products" }), {
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
      container.querySelectorAll("input[role='searchbox']"),
    ).toHaveLength(1);
    expect(
      container.querySelector(".discover-hero .discover-search input"),
    ).toBe(screen.getByRole("searchbox", { name: "Search products" }));
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
    // No product counts on the tiles: the merchandising doors above carry the
    // live numbers, so the rail stays a visual path rather than a table.
    expect(
      container.querySelector(".discover-intention-rail")?.textContent,
    ).not.toMatch(/\d/);
  });

  it("opens with an invitation rather than a product model", () => {
    // The headline promises "Search naturally" and the field then cycled through
    // "Sonora WH-C720" and "Mosaic Auraluxe H9" as ghost text, which reads as a
    // demo fixture. Cold start asks for the thing the hero just promised.
    const { container } = renderPage();
    const input = screen.getByRole("searchbox", { name: "Search products" });

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

  it("keeps editorial search free of typeahead work and overlays", () => {
    renderPage();
    const input = screen.getByRole("searchbox", { name: "Search products" });

    fireEvent.change(input, { target: { value: "sono" } });
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(api.suggestions).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders the editorial Shop preview without requesting its products", () => {
    renderPage();

    // One shopping section, not two. The category tiles used to carry their own
    // "Shop with intention" heading directly above this one.
    expect(screen.getByRole("heading", { name: "Shop with intention" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: /Shop with intention/ })).toHaveLength(1);
    expect(screen.getByText("Browse a category with its filter already set.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Auraluxe H9" })).toBeTruthy();
    expect(screen.getByText("4.8")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Shop all" }).getAttribute("href")).toBe("/catalog");
    // The preview above rendered synchronously from showcase data. The only
    // catalog requests Discover makes on mount are the merchandising count
    // reads (one per door, limit 1) and the editorial pick reads (one per
    // story, limit 3) — never a page of preview products.
    const calls = vi.mocked(api.catalog).mock.calls;
    expect(calls).toHaveLength(
      merchandisingDoors.length + editorialStories.length,
    );
    for (const call of calls) {
      expect(call[1]).toBe(0);
      expect([1, 3]).toContain(call[2]);
    }
  });

  it("opens merchandising doors with live counts routed through Shop's params", async () => {
    const totals: Record<string, number> = {
      max_price_cents: 1243,
      in_stock_only: 861,
      min_rating: 402,
    };
    vi.mocked(api.catalog).mockImplementation((filters: SearchFilters) => {
      const key = Object.keys(filters)[0];
      return Promise.resolve(countPage(totals[key]));
    });
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelectorAll(".discover-merch-door")).toHaveLength(3);
    });
    const doors = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".discover-merch-door"),
    );
    expect(doors.map((door) => door.getAttribute("href"))).toEqual([
      "/catalog?max_price_cents=20000",
      "/catalog?in_stock_only=true",
      "/catalog?min_rating=4",
    ]);
    // Counts are the doors' own limit-1 totals, formatted for reading.
    expect(doors.map((door) => door.querySelector(".discover-merch-count")?.textContent))
      .toEqual(["1,243", "861", "402"]);
    expect(screen.getByText("Shop by what matters")).toBeTruthy();
  });

  it("keeps a door shut when its count is zero", async () => {
    vi.mocked(api.catalog).mockImplementation((filters: SearchFilters) =>
      Promise.resolve(countPage("in_stock_only" in filters ? 0 : 57)),
    );
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelectorAll(".discover-merch-door")).toHaveLength(2);
    });
    expect(screen.queryByText("In stock now")).toBeNull();
  });

  it("prints the social-proof line only from a live summary", async () => {
    vi.mocked(api.summary).mockResolvedValue(summaryFixture);
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelector(".discover-merch-proof")).toBeTruthy();
    });
    const proof = container.querySelector(".discover-merch-proof")!;
    expect(proof.textContent).toContain("4.6");
    expect(proof.textContent).toContain("average across 128,412 customer reviews");
  });

  it("hides the merchandising band entirely when the live reads fail", async () => {
    // No skeletons, no placeholders, no invented numbers: a band that cannot
    // prove its figures does not render.
    vi.mocked(api.catalog).mockRejectedValue(new Error("api down"));
    vi.mocked(api.summary).mockRejectedValue(new Error("api down"));
    const { container } = renderPage();

    await waitFor(() => {
      expect(vi.mocked(api.catalog)).toHaveBeenCalledTimes(
        merchandisingDoors.length + editorialStories.length,
      );
      expect(vi.mocked(api.summary)).toHaveBeenCalledTimes(1);
    });
    expect(container.querySelector(".discover-merch")).toBeNull();
    // The editorial picks are live reads over the same endpoint, so a failure
    // leaves the stories with their copy alone rather than placeholder rows.
    expect(container.querySelector(".discover-editorial-picks")).toBeNull();
  });

  it("quotes real customer voices with the products they reviewed", async () => {
    vi.mocked(api.reviewHighlights).mockResolvedValue(voicesFixture);
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelector(".discover-voice blockquote")).toBeTruthy();
    });
    const quote = container.querySelector(".discover-voice blockquote")!;
    expect(quote.textContent).toContain(voicesFixture[0].quote);
    const caption = container.querySelector(".discover-voice figcaption")!;
    expect(caption.textContent).toContain("5.0");
    expect(caption.textContent).toContain("Verified purchase");
    expect(caption.querySelector("a")?.getAttribute("href")).toBe("/products/501");

    // The dots are the manual way through the same three voices.
    const dots = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".discover-voices-dots button"),
    );
    expect(dots).toHaveLength(3);
    fireEvent.click(dots[1]);
    expect(
      container.querySelector(".discover-voice blockquote")?.textContent,
    ).toContain(voicesFixture[1].quote);
  });

  it("advances to the next voice on its own", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.reviewHighlights).mockResolvedValue(voicesFixture);
      const { container } = renderPage();
      await act(async () => {});

      expect(
        container.querySelector(".discover-voice blockquote")?.textContent,
      ).toContain(voicesFixture[0].quote);
      act(() => {
        vi.advanceTimersByTime(6500);
      });
      expect(
        container.querySelector(".discover-voice blockquote")?.textContent,
      ).toContain(voicesFixture[1].quote);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no voices strip when the highlights read fails", async () => {
    // A quotation placeholder would be an invented customer, so a failed read
    // leaves the strip out entirely.
    vi.mocked(api.reviewHighlights).mockRejectedValue(new Error("api down"));
    const { container } = renderPage();

    await waitFor(() => {
      expect(vi.mocked(api.reviewHighlights)).toHaveBeenCalledTimes(1);
    });
    expect(container.querySelector(".discover-voices")).toBeNull();
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

  it("fills each editorial story with live picks from its own category", async () => {
    let nextId = 9000;
    vi.mocked(api.catalog).mockImplementation(
      (filters: SearchFilters, offset = 0, limit = 12) => {
        // The limit-1 door counts stay pending; the limit-3 story reads answer
        // with one top-rated pick each.
        if (limit !== 3) return new Promise<CatalogPage>(() => {});
        nextId += 1;
        return Promise.resolve({
          total: 1,
          offset,
          limit,
          products: [pickFixture(nextId, filters)],
          facets: {},
        });
      },
    );
    const { container } = renderPage();

    await waitFor(() => {
      expect(
        container.querySelectorAll(".discover-editorial-picks"),
      ).toHaveLength(editorialStories.length);
    });
    const rows = Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".discover-editorial-picks a"),
    );
    expect(rows).toHaveLength(editorialStories.length);
    // The first story is the over-ear headphones edit, and its row links to a
    // real product page with the price alongside the title.
    expect(rows[0].getAttribute("href")).toBe("/products/9001");
    expect(rows[0].textContent).toContain("Top-rated over-ear-headphones");
    expect(rows[0].textContent).toContain("$249.00");
  });

  it("shops every storefront errand through one arrowless maroon button", () => {
    const { container } = renderPage();

    // Three story buttons, "Shop all", the running & fitness plate link, and
    // the labs band's inverted pill — one shared treatment, no trailing arrows.
    const ctas = Array.from(container.querySelectorAll(".discover-cta"));
    expect(ctas).toHaveLength(editorialStories.length + 3);
    for (const cta of ctas) {
      expect(cta.querySelector("svg")).toBeNull();
    }

    // The story button runs the same constrained query as its photograph.
    fireEvent.click(
      screen.getByRole("button", { name: "Shop running & fitness" }),
    );
    expect(window.location.pathname).toBe("/catalog");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe(
      "Recovery tools for sore calves after long runs that fit in a carry-on.",
    );
    expect(params.get("domain")).toBe("running_fitness");
    expect(params.get("category_key")).toBe("mobility-tools");
  });

});
