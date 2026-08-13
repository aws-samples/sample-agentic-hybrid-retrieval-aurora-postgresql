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
import { showcaseCatalogPage, showcaseProductDetail } from "../showcase";
import { DiscoverPage } from "./DiscoverPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
  },
}));

const chair = showcaseProductDetail(370001)!;
const display = showcaseProductDetail(420001)!;
const keyboard = {
  ...chair,
  product_id: 429001,
  title: "Keysmith MX Quiet Mechanical Wireless Keyboard",
  model: "MX Quiet",
  brand: "Keysmith",
  sku: "KEY-MX-QUIET",
  category_key: "quiet-keyboards",
  category_path: "Workspace > Input Devices > Quiet Keyboards",
  price_cents: 16999,
  short_description: "Quiet mechanical input for focused work.",
  long_description: "A quiet mechanical keyboard for long, focused workdays.",
  attributes: { quiet_typing: true, wireless: true },
};

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.product).mockReset();
    vi.mocked(api.catalog).mockResolvedValue(showcaseCatalogPage({}, 0, 4));
    vi.mocked(api.product).mockImplementation(async (productId) => {
      const product = new Map([
        [370001, chair],
        [420001, display],
        [429001, keyboard],
      ]).get(productId);
      if (!product) throw new Error(`Unexpected studio product ${productId}`);
      return product;
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
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), {
      target: { value: "quiet keyboard under $180" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search Mosaic" }));

    expect(window.location.pathname).toBe("/catalog");
    expect(new URLSearchParams(window.location.search).get("q")).toBe(
      "quiet keyboard under $180",
    );
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

  it("keeps the optional creative studio interactive and hands off to Shop", async () => {
    renderPage();

    await waitFor(() => {
      expect(api.product).toHaveBeenCalledTimes(3);
    });

    const assemble = await screen.findByRole("button", {
      name: "Assemble the studio",
    });
    fireEvent.click(assemble);

    expect(screen.getByRole("link", { name: /Forma Ergonomic/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Atelier 32/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /MX Quiet/ })).toBeTruthy();
    expect(screen.getByText("Studio assembled")).toBeTruthy();

    const workspace = screen.getByRole("link", { name: "Shop the workspace" });
    const params = new URLSearchParams(workspace.getAttribute("href")?.split("?")[1]);
    expect(params.get("domain")).toBe("home_office");
    expect(params.get("q")).toBeNull();
  });
});
