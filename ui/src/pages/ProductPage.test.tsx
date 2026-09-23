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
    similarProducts: vi.fn(),
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
    vi.mocked(api.similarProducts).mockReset();
    vi.mocked(api.similarProducts).mockResolvedValue(showcaseCatalogPage({}, 0, 5).products);
  });

  afterEach(cleanup);

  it("keeps original listing content available without repeating it in the opening view", async () => {
    const base = showcaseProductDetail(1)!;
    const title = "Original headphone case compatible with several headphone models, with a hard shell and a storage pocket for accessories — original source title";
    const product: ProductDetail = {
      ...base,
      title,
      source_dataset: "reviews-2023-500k-v1",
      image_url: "https://example.com/original-front.jpg",
      image_source: "original_listing",
      listing_url: "https://www.amazon.com/dp/SOURCE0001",
      long_description: "Unchanged original description. ".repeat(25),
      short_description: "Unchanged original description. ".repeat(25),
      source_features: ["A case only; headphones are not included."],
      price_cents: null,
      availability: null,
      inventory_count: null,
      attributes: { Color: "Grey" },
      media: [
        { role: "gallery", sort_order: 1, image_url: "https://example.com/original-open.jpg", image_source: "original_listing", image_key: "open", alt_text: "Open case" },
      ],
      reviews: [],
    };
    vi.mocked(api.product).mockResolvedValue(product);
    vi.mocked(api.similarProducts).mockResolvedValue([]);
    const { container } = render(<CommerceProvider><ProductPage /></CommerceProvider>);
    const heading = await screen.findByRole("heading", { name: title });
    expect(heading.textContent).toBe(title);
    expect(heading.className).toBe("source-title-preview");
    fireEvent.click(screen.getByRole("button", { name: "Show full product name" }));
    expect(heading.className).toBe("");
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");

    expect(container.querySelector(".source-detail-summary")?.textContent).not.toContain(product.long_description);
    expect(screen.getAllByText(product.long_description.trim())).toHaveLength(1);
    expect(container.querySelector(".source-detail-information details")?.hasAttribute("open")).toBe(false);
    expect(screen.queryByRole("button", { name: "Add to cart" })).toBeNull();
    expect(screen.getByRole("link", { name: "View original listing" }).getAttribute("href")).toBe(product.listing_url);
    expect(screen.getByText(/No review text was imported for this listing/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "View product image 2" }));
    expect(container.querySelector(".source-detail-photo > img")?.getAttribute("src")).toBe("https://example.com/original-open.jpg");
  });

  it("labels imported reviews as a selection beside the source rating count", async () => {
    const base = showcaseProductDetail(1)!;
    const product: ProductDetail = {
      ...base,
      title: "Original monitor listing",
      source_dataset: "reviews-2023-500k-v1",
      listing_url: "https://www.amazon.com/dp/SOURCE0002",
      rating: 5,
      review_count: 6,
      reviews: [
        {
          review_id: 9101,
          rating: 5,
          title: "Charges my laptop",
          body: "One USB-C cable carries display and power.",
          verified_purchase: true,
          helpful_votes: 3,
          review_date: "2022-03-01",
          sentiment_score: null,
          source_uri: "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023",
          source_name: "Amazon Reviews 2023",
        },
      ],
    };
    vi.mocked(api.product).mockResolvedValue(product);
    vi.mocked(api.similarProducts).mockResolvedValue([]);
    render(<CommerceProvider><ProductPage /></CommerceProvider>);

    await screen.findByRole("heading", { name: "Original monitor listing" });
    expect(screen.getByText("1 shown of 6 ratings")).toBeTruthy();
    expect(screen.getByText(/not a representative sample/)).toBeTruthy();
    expect(screen.getByText("Not reported: unknown, not free")).toBeTruthy();
  });

  it("labels false attributes accurately and opens the actual source records", async () => {
    const product = showcaseProductDetail(1);
    if (!product) throw new Error("Missing product fixture");
    vi.mocked(api.product).mockResolvedValue({ ...product, attributes: { wireless: false, connection: "USB-C" } });
    const scroll = vi.fn();
    const { container } = render(<CommerceProvider><ProductPage /></CommerceProvider>);
    await screen.findByRole("heading", { name: product.title });
    const facts = container.querySelector(".product-key-facts")!;
    expect(facts.querySelector("dt")?.textContent).toBe("wireless");
    expect(facts.querySelector("dd")?.textContent).toBe("No");
    expect(facts.textContent).toContain("connectionUSB-C");

    const information = container.querySelector<HTMLElement>("#product-information")!;
    information.scrollIntoView = scroll;
    fireEvent.click(screen.getByRole("button", { name: "Inspect source records" }));
    const tab = container.querySelector("#product-tab-evidence")!;
    expect(tab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab);
    expect(scroll).toHaveBeenCalledWith({ block: "start" });
    expect(container.querySelector('[role="tabpanel"]')?.getAttribute("aria-labelledby"))
      .toBe("product-tab-evidence");
  });

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
    vi.mocked(api.similarProducts).mockReturnValue(new Promise(() => {}));

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
    vi.mocked(api.similarProducts)
      .mockRejectedValueOnce(new Error("related catalog unavailable"))
      .mockResolvedValueOnce(relatedPage.products);

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

    expect(await screen.findByRole("heading", { name: "Similar headphones" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: product.title })).toBeTruthy();
    expect(api.similarProducts).toHaveBeenCalledTimes(2);
  });

  it("returns to the carried catalog context even after another product page", async () => {
    const product = showcaseProductDetail(1);
    if (!product) throw new Error("Missing product return fixture");
    vi.mocked(api.product).mockResolvedValue(product);
    window.history.replaceState(
      {},
      "",
      "/catalog?domain=consumer_electronics&brand=Mosaic&q=headphones",
    );
    window.history.pushState({}, "", "/products/17001");
    window.history.pushState({}, "", "/products/1?from=" + encodeURIComponent("/catalog?domain=consumer_electronics&brand=Mosaic&q=headphones"));

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    const back = await screen.findByRole("link", { name: "Back to catalog" });
    expect(back.getAttribute("href")).toContain("domain=consumer_electronics");
    expect(back.getAttribute("href")).toContain("brand=Mosaic");
    fireEvent.click(back);

    await waitFor(() => expect(window.location.pathname).toBe("/catalog"));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("brand")).toBe("Mosaic");
    expect(params.get("q")).toBe("headphones");
  });

  it("saves the current product and only displays its actual warranty", async () => {
    const product = showcaseProductDetail(1)!;
    vi.mocked(api.product).mockResolvedValue({ ...product, warranty_months: 18 });
    render(<CommerceProvider><ProductPage /></CommerceProvider>);
    await screen.findByRole("heading", { name: product.title });
    const save = screen.getByRole("button", { name: `Save ${product.title}` });
    fireEvent.click(save);
    expect(save.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("18-month warranty")).toBeTruthy();
    expect(screen.queryByText("2-year warranty")).toBeNull();
    expect(screen.queryByText("60-day free returns")).toBeNull();
    expect(document.querySelector(".product-main-image img")?.getAttribute("alt")).toBe(product.title);
    fireEvent.click(save);
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
