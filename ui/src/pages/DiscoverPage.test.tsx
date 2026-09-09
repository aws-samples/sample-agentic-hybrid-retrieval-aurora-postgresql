// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { createDiscoverData, discoverData, preloadDiscover } from "../discoverData";
import { mosaicLabManifest } from "../labMissions";
import type { ReadinessResponse } from "../types";
import { DiscoverPage } from "./DiscoverPage";

vi.mock("../api", () => ({
  api: { catalog: vi.fn(), suggestions: vi.fn(), readiness: vi.fn() },
}));

function renderPage() {
  return render(<DiscoverPage />);
}

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    Object.assign(discoverData, createDiscoverData());
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.suggestions).mockReset();
    vi.mocked(api.readiness).mockReset();
    vi.mocked(api.readiness).mockResolvedValue({ database: { product_count: 500_000 } } as ReadinessResponse);
  });
  afterEach(cleanup);

  it("routes a typed product need into Shop retrieval without imposing Alex’s categories", () => {
    renderPage();
    const input = screen.getByRole("searchbox", { name: "Search products" });
    fireEvent.change(input, { target: { value: "a monitor for my home office" } });
    fireEvent.submit(input.closest("form")!);
    expect(window.location.pathname).toBe("/catalog");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("a monitor for my home office");
    expect(params.get("view")).toBe("results");
    expect(params.get("domain")).toBeNull();
  });

  it("puts one search field in the hero and keeps typeahead overlays out", () => {
    const { container } = renderPage();
    const input = screen.getByRole("searchbox", { name: "Search products" });
    expect(container.querySelector(".discover-hero")?.contains(input)).toBe(true);
    expect(screen.getAllByRole("searchbox")).toHaveLength(1);
    expect((input as HTMLInputElement).value).toBe("");
    fireEvent.change(input, { target: { value: "sono" } });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(api.suggestions).not.toHaveBeenCalled();
  });

  it("keeps lab instructions and exercise links out of Discover", () => {
    const { container } = renderPage();
    expect(screen.queryByRole("heading", { name: "Run your lab's request" })).toBeNull();
    expect(container.textContent).not.toMatch(/Follow the guide|Retrieve|Reranked shortlist|Grounded recommendation/);
    for (const link of screen.getAllByRole("link")) {
      const url = new URL(link.getAttribute("href")!, "http://localhost");
      expect(url.pathname).not.toMatch(/^\/(?:labs|mosaic-labs)(?:\/|$)/);
      expect(url.searchParams.has("mission")).toBe(false);
    }
  });

  it("introduces Alex’s brief without fetching inventory or pretending to track completion", () => {
    const { container } = renderPage();
    expect(screen.getByRole("heading", { name: "Meet Alex." })).toBeTruthy();
    expect(screen.getByText("Already in place")).toBeTruthy();
    expect(screen.getByText("Desk")).toBeTruthy();
    expect(screen.getByText("Laptop")).toBeTruthy();
    expect(screen.getByText("Still to choose")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(container.textContent).not.toMatch(/2 of 7|Atelier 32/);
    expect(container.querySelector(".shop-product-card")).toBeNull();
    expect(api.catalog).not.toHaveBeenCalled();
    const briefLink = screen.getByRole("link", { name: "Explore Alex’s brief" });
    expect(document.querySelector(briefLink.getAttribute("href")!)?.querySelectorAll("article")).toHaveLength(3);
  });

  it("keeps the essential categories in the same order as Alex’s needs", () => {
    const { container } = renderPage();
    const categories = within(screen.getByRole("navigation", { name: "Workspace categories" }));
    expect(categories.getAllByRole("link").map(link => link.textContent)).toEqual([
      "Headphones", "Chairs", "Keyboards",
    ]);
    expect(container.textContent).not.toMatch(/running|fitness|shoes|treadmill/i);
    expect([...container.querySelectorAll("img")].map(image => image.src).join(" ")).not.toMatch(/fitness|running|shoes/);
  });

  it("links each category to the correct domain, including cross-domain audio", () => {
    renderPage();
    const categories = within(screen.getByRole("navigation", { name: "Workspace categories" }));
    expect(categories.getByRole("link", { name: "Keyboards" }).getAttribute("href")).toBe(
      "/catalog?domain=home_office&category_key=quiet-keyboards",
    );
    expect(categories.getByRole("link", { name: "Chairs" }).getAttribute("href")).toBe(
      "/catalog?domain=home_office&category_key=ergonomic-office-chairs",
    );
    expect(categories.getByRole("link", { name: "Headphones" }).getAttribute("href")).toBe(
      "/catalog?domain=consumer_electronics&category_key=over-ear-headphones",
    );
  });

  it("routes every illustrated need and its action to the same scoped request as Shop", () => {
    const { container } = renderPage();
    const needs = [...container.querySelectorAll(".discover-need")];
    expect(needs).toHaveLength(3);
    const requests = mosaicLabManifest.playground.requests.filter(request => request.id !== "exact-model");
    for (const [index, need] of needs.entries()) {
      const request = requests[index];
      expect(need.querySelector("img")).toBeTruthy();
      expect(need.querySelector(".discover-category-tile")?.querySelector("button, a")).toBeNull();
      const links = within(need as HTMLElement).getAllByRole("link");
      expect(links).toHaveLength(2);
      for (const link of links) {
        const url = new URL(link.getAttribute("href")!, "http://localhost");
        expect(url.pathname).toBe("/catalog");
        expect(url.searchParams.get("view")).toBe("results");
        expect(url.searchParams.get("q")).toBe(request.query);
        expect(url.searchParams.get("category_key")).toBe(request.filters.category_key);
        expect(url.searchParams.get("domain")).toBe(request.filters.domain);
      }
    }
  });

  it("shares the live corpus-count read across prefetch and return navigation", async () => {
    vi.mocked(api.readiness).mockResolvedValue({ database: { product_count: 498_731 } } as ReadinessResponse);
    preloadDiscover();
    const first = renderPage();
    await screen.findByText("Search 498,731 products");
    first.unmount();
    renderPage();
    await screen.findByText("Search 498,731 products");
    expect(api.readiness).toHaveBeenCalledTimes(1);
    expect(api.catalog).not.toHaveBeenCalled();
  });

  it("keeps the brief and search usable if the live corpus count is unavailable", async () => {
    vi.mocked(api.readiness).mockRejectedValue(new Error("Unavailable"));
    renderPage();
    await waitFor(() => expect(api.readiness).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Search [\d,]+ products/)).toBeNull();
    expect(screen.getByRole("searchbox")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Find headphones for Alex" })).toBeTruthy();
  });

  it("keeps implementation vocabulary off the storefront", () => {
    const { container } = renderPage();
    for (const term of ["FTS", "pg_trgm", "pgvector", "HNSW", "RRF", "tsvector"]) {
      expect(container.textContent).not.toContain(term);
    }
  });
});
