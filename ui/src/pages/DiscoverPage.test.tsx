// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { DiscoverPage } from "./DiscoverPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
  },
}));

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.mocked(api.catalog).mockReset();
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

    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), {
      target: { value: "quiet keyboard under $180" },
    });
    expect(
      container.querySelector(".discover-search .generative-search-icon"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Search Mosaic" }));

    expect(window.location.pathname).toBe("/catalog");
    expect(new URLSearchParams(window.location.search).get("q")).toBe(
      "quiet keyboard under $180",
    );
  });

  it("labels the hero action for search and focuses the catalog query", () => {
    renderPage();

    const searchInput = screen.getByRole("textbox", { name: "Search products" });
    searchInput.scrollIntoView = vi.fn();
    fireEvent.click(
      screen.getByRole("button", { name: "Search the catalog" }),
    );

    expect(document.activeElement).toBe(searchInput);
    expect(searchInput.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "center",
    });
    expect(screen.queryByText("Explore collections")).toBeNull();
  });

  it("renders the editorial Shop preview immediately without a catalog request", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Shop" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Auraluxe H9" })).toBeTruthy();
    expect(screen.getByText("4.8")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Shop all" }).getAttribute("href")).toBe("/catalog");
    expect(vi.mocked(api.catalog)).not.toHaveBeenCalled();
  });

  it("previews Mosaic Labs with product-led retrieval, ranking, and evidence scenes", () => {
    const { container } = renderPage();

    expect(
      screen.getByText("Start with one of these three example searches."),
    ).toBeTruthy();
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
