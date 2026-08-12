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
    category_key: "over-ear-headphones",
    category_path: "Audio > Over-Ear Headphones",
    brand: "Test",
    model: "T-1",
    price_cents: 10000,
    list_price_cents: 12000,
    currency: "USD",
    rating: 4.5,
    review_count: 10,
    availability: "in_stock",
    inventory_count: 5,
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
    ...overrides,
  };
}

describe("productImage", () => {
  it("preserves an API-owned local image path", () => {
    expect(productImage(product({
      product_id: 999999,
      image_url: "/assets/images/custom.webp",
    }))).toBe(
      "/assets/images/custom.webp",
    );
  });

  it("uses the verified 3:2 cohort asset instead of a legacy square image", () => {
    expect(
      productImage(product({
        product_id: 1,
        image_url: "/assets/images/mosaic/auraluxe-h9.webp",
      })),
    ).toBe(
      "/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp",
    );
  });

  it("uses a screened chair photograph for chair subcategories", () => {
    expect(
      productImage(
        product({
          domain: "home_office",
          category_key: "ergonomic-office-chairs",
          category_path: "Seating > Ergonomic Office Chairs",
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
          category_key: "road-running-shoes",
          category_path: "Footwear > Road Running Shoes",
        }),
      ),
    ).toMatch(/^\/assets\/images\/(?:mosaic|curated)\/[\w-]+\.webp$/);
  });

  it("falls back to the domain image when nothing matches", () => {
    expect(
      productImage(
        product({
          product_id: 999998,
          domain: "home_office",
          category_key: "cable-management",
          category_path: "Desk Accessories > Cable Management",
          title: "Cable tidy",
          brand: "Test",
        }),
      ),
    ).toBe("/assets/images/mosaic/forma-ergonomic-studio.webp");
  });

  it("spreads repeated subcategories across distinct photographs", () => {
    // A results grid showing the same picture four times reads as placeholder
    // data, so the picker keys on product_id.
    const images = new Set(
      [1, 2, 3, 4].map((product_id) =>
        productImage(product({ product_id, category_path: "Audio > Over-Ear Headphones" })),
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
            category_path: "Audio > Over-Ear Headphones",
          }),
        ),
      );
      expect(new Set(picks).size, `stride ${stride}`).toBeGreaterThan(2);
    }
  });
});
