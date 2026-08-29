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
import { showcaseCatalogPage, showcaseProductDetail } from "../showcase";
import type { ProductDetail } from "../types";
import { ProductPage } from "./ProductPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
  },
}));

type DeferredProduct = {
  promise: Promise<ProductDetail>;
  resolve: (product: ProductDetail) => void;
};

function deferredProduct(): DeferredProduct {
  let resolve!: (product: ProductDetail) => void;
  const promise = new Promise<ProductDetail>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("ProductPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/products/1");
    vi.mocked(api.product).mockReset();
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.catalog).mockResolvedValue(showcaseCatalogPage({}, 0, 5));
  });

  afterEach(cleanup);

  it("ignores an older product response after the route changes", async () => {
    const first = deferredProduct();
    const second = deferredProduct();
    vi.mocked(api.product).mockImplementation((productId) => (
      productId === 1 ? first.promise : second.promise
    ));

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    await waitFor(() => expect(api.product).toHaveBeenCalledWith(1));
    window.history.pushState({}, "", "/products/17001");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(api.product).toHaveBeenCalledWith(17001));

    const echoBud = showcaseProductDetail(17001);
    const auraluxe = showcaseProductDetail(1);
    if (!echoBud || !auraluxe) throw new Error("Missing product race fixtures");

    await act(async () => {
      second.resolve(echoBud);
      await second.promise;
    });
    expect(
      await screen.findByRole("heading", { name: "Mosaic EchoBud S2" }),
    ).toBeTruthy();

    await act(async () => {
      first.resolve(auraluxe);
      await first.promise;
    });
    expect(
      screen.getByRole("heading", { name: "Mosaic EchoBud S2" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Mosaic Auraluxe H9" }),
    ).toBeNull();
  });

  it("renders nullable review evidence without an empty date separator", async () => {
    const base = showcaseProductDetail(17001);
    if (!base) throw new Error("Missing product review fixture");
    const product = {
      ...base,
      reviews: [
        {
          review_id: 9001,
          rating: null,
          title: null,
          body: "Comfortable for long listening sessions.",
          verified_purchase: false,
          helpful_votes: 0,
          review_date: null,
          sentiment_score: null,
          source_uri: "mosaic://evidence/9001",
          source_name: "Mosaic catalog",
        },
      ],
    } satisfies ProductDetail;
    vi.mocked(api.product).mockResolvedValue(product);

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    await screen.findByRole("heading", { name: "Mosaic EchoBud S2" });
    fireEvent.click(screen.getByRole("tab", { name: "Reviews (1)" }));

    expect(document.querySelector(".review-list cite")?.textContent).toBe(
      "Mosaic catalog",
    );
    expect(document.querySelector(".review-list .rating-row")).toBeNull();
  });

  it("renders primary detail without waiting for related products", async () => {
    const product = showcaseProductDetail(1);
    if (!product) throw new Error("Missing primary product fixture");
    vi.mocked(api.product).mockResolvedValue(product);
    vi.mocked(api.catalog).mockReturnValue(new Promise(() => {}));

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: product.title }),
    ).toBeTruthy();
    expect(screen.getByText("Loading related products")).toBeTruthy();
    expect(screen.queryByText("Loading product evidence")).toBeNull();
  });

  it("retries related products without replacing primary detail", async () => {
    const product = showcaseProductDetail(1);
    if (!product) throw new Error("Missing primary product fixture");
    const relatedPage = showcaseCatalogPage({}, 0, 5);
    vi.mocked(api.product).mockResolvedValue(product);
    vi.mocked(api.catalog)
      .mockRejectedValueOnce(new Error("related catalog unavailable"))
      .mockResolvedValueOnce(relatedPage);

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    expect(await screen.findByRole("heading", { name: product.title })).toBeTruthy();
    const error = await screen.findByText("related catalog unavailable");
    const panel = error.closest(".related-products");
    if (!panel) throw new Error("Missing related-product error panel");
    fireEvent.click(panel.querySelector("button")!);

    expect(await screen.findByRole("heading", { name: "You may also like" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: product.title })).toBeTruthy();
    expect(api.catalog).toHaveBeenCalledTimes(2);
  });

  it("returns through browser history so catalog filters and search context survive", async () => {
    const product = showcaseProductDetail(1);
    if (!product) throw new Error("Missing product return fixture");
    vi.mocked(api.product).mockResolvedValue(product);
    window.history.replaceState(
      {},
      "",
      "/catalog?domain=consumer_electronics&brand=Mosaic&q=headphones",
    );
    window.history.pushState({}, "", "/products/1");

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    const back = await screen.findByRole("link", { name: "Back to catalog" });
    expect(back.getAttribute("href")).toContain("domain=consumer_electronics");
    expect(back.getAttribute("href")).toContain("category_key=");
    fireEvent.click(back);

    await waitFor(() => expect(window.location.pathname).toBe("/catalog"));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("brand")).toBe("Mosaic");
    expect(params.get("q")).toBe("headphones");
  });

  it("exposes selected image and tab state and supports tab keyboard navigation", async () => {
    const base = showcaseProductDetail(1);
    if (!base) throw new Error("Missing selected-control fixture");
    const product: ProductDetail = {
      ...base,
      media: [
        ...base.media,
        {
          role: "gallery",
          sort_order: base.media.length,
          image_url: "/assets/images/mosaic/selected-control-secondary.webp",
          image_source: "selected-control-test",
          image_key: "selected-control-secondary",
          alt_text: `${base.title} secondary view`,
        },
      ],
    };
    vi.mocked(api.product).mockResolvedValue(product);

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    await screen.findByRole("heading", { name: product.title });
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs[1]);
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(
      tabs[1].id,
    );

    const imageButtons = screen.queryAllByRole("button", {
      name: /View product image/,
    });
    expect(imageButtons.length).toBeGreaterThan(1);
    expect(imageButtons[0].getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(imageButtons[1]);
    expect(imageButtons[1].getAttribute("aria-pressed")).toBe("true");
    expect(imageButtons[0].getAttribute("aria-pressed")).toBe("false");
  });
});
