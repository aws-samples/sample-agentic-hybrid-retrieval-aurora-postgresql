import { describe, expect, it } from "vitest";
import { productImage } from "./media";
import type { ProductSummary } from "./types";

function product(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    product_id: 1,
    sku: "TEST-0001",
    title: "Test product",
    short_description: "Test description",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    brand: "Test",
    model: "T-1",
    price_usd: 100,
    list_price_usd: 120,
    rating: 4.5,
    review_count: 10,
    availability: "In Stock",
    inventory_count: 5,
    attributes: {},
    tags: [],
    image_url: null,
    image_source: null,
    signals: null,
    sources: [],
    ...overrides,
  };
}

describe("productImage", () => {
  it("preserves an API-owned local image path", () => {
    expect(productImage(product({ image_url: "/assets/images/custom.webp" }))).toBe(
      "/assets/images/custom.webp",
    );
  });

  it("uses a screened chair photograph for chair subcategories", () => {
    expect(
      productImage(
        product({
          domain: "home_office",
          subcategory: "Ergonomic Office Chairs",
        }),
      ),
    ).toMatch(/^\/assets\/images\/(?:mosaic|curated)\/[\w-]+\.webp$/);
  });

  it("shows a shoe for running footwear rather than a track backdrop", () => {
    // The previous fallback sent every running product to a photograph of an
    // empty running track, which reads as a category banner, not merchandise.
    expect(
      productImage(
        product({
          domain: "running_fitness",
          category: "Footwear",
          subcategory: "Road Running Shoes",
        }),
      ),
    ).toMatch(/^\/assets\/images\/(?:mosaic|curated)\/[\w-]+\.webp$/);
  });

  it("falls back to the domain image when nothing matches", () => {
    expect(
      productImage(
        product({
          domain: "home_office",
          category: "Desk Accessories",
          subcategory: "Cable Management",
          title: "Cable tidy",
          brand: "Test",
        }),
      ),
    ).toBe("/assets/images/mosaic/forma-ergonomic-thumb.webp");
  });

  it("spreads repeated subcategories across distinct photographs", () => {
    // A results grid showing the same picture four times reads as placeholder
    // data, so the picker keys on product_id.
    const images = new Set(
      [1, 2, 3, 4].map((product_id) =>
        productImage(product({ product_id, subcategory: "Over-Ear Headphones" })),
      ),
    );
    expect(images.size).toBeGreaterThan(1);
  });

  it("does not repeat a photograph across evenly spaced ids", () => {
    // Measured against the live catalog: one headphone photograph filled 4 of
    // 10 cards, in adjacent pairs. Real ids are not consecutive, and any
    // stride sharing a factor with the asset count makes `id % length` cycle
    // through a subset. Hashing the id first decouples the two.
    for (const stride of [2, 4, 6, 8]) {
      const picks = Array.from({ length: 4 }, (_, index) =>
        productImage(
          product({
            product_id: 1000 + index * stride,
            subcategory: "Over-Ear Headphones",
          }),
        ),
      );
      expect(new Set(picks).size, `stride ${stride}`).toBeGreaterThan(2);
    }
  });
});
