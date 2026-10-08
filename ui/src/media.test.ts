import { describe, expect, it } from "vitest";
import { domainIllustration, productImage, productImageMap } from "./media";
import type { Domain, ProductSummary } from "./types";

const UNAVAILABLE = "/assets/images/product-unavailable.svg";

function product(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    product_id: 1492978,
    sku: "B0C2WWCFQB",
    title: "Logitech Zone 900",
    short_description: "Test description",
    domain: "consumer_electronics",
    category_key: "headphones",
    category_path: "Electronics > Headphones",
    brand: "Logitech",
    model: "Zone 900",
    price_cents: 10000,
    list_price_cents: 12000,
    currency: "USD",
    rating: 4.5,
    review_count: 10,
    availability: null,
    inventory_count: null,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: false,
    is_retrieval_anchor: false,
    image_url: "https://m.media-amazon.com/images/I/zone-900.jpg",
    image_source: "original_listing",
    source_dataset: "reviews-2023-v2",
    signals: null,
    sources: [],
    ...overrides,
  };
}

function listing(index: number): ProductSummary {
  return product({
    product_id: 1_000_001 + index,
    image_url: `https://m.media-amazon.com/images/I/listing-${index}.jpg`,
  });
}

describe("productImage", () => {
  it("shows the listing's own photograph", () => {
    expect(productImage(product())).toBe("https://m.media-amazon.com/images/I/zone-900.jpg");
  });

  it.each([null, ""])("shows the unavailable placeholder when the listing photo is %j", (image_url) => {
    expect(productImage(product({ image_url }))).toBe(UNAVAILABLE);
  });

  it("does not substitute a retired showcase photograph by ID or title", () => {
    // Product 1 and the title "Auraluxe H9" both selected Mosaic showcase
    // photography before the synthetic catalog was retired.
    const legacy = product({ product_id: 1, title: "Auraluxe H9", source_dataset: null, image_url: null });
    expect(productImage(legacy)).toBe(UNAVAILABLE);
  });
});

describe("productImageMap", () => {
  it("keeps each photo when ranking reverses the result order", () => {
    const rows = Array.from({ length: 12 }, (_, index) => listing(index));
    expect(productImageMap([...rows].reverse())).toEqual(productImageMap(rows));
  });

  it("keeps Shop photos when Reason selects a smaller shortlist or a single product", () => {
    const rows = Array.from({ length: 12 }, (_, index) => listing(index));
    const shopImages = productImageMap(rows);
    const picks = rows.filter((_, index) => index % 3 === 0).reverse();
    for (const row of picks) {
      expect(productImageMap(picks).get(row.product_id)).toBe(shopImages.get(row.product_id));
      expect(productImageMap([row]).get(row.product_id)).toBe(shopImages.get(row.product_id));
    }
  });

  it("maps a product that appears twice once", () => {
    const row = listing(0);
    expect([...productImageMap([row, row]).keys()]).toEqual([row.product_id]);
  });
});

describe("domainIllustration", () => {
  it.each<Domain>(["consumer_electronics", "running_fitness", "home_office"])(
    "uses the %s still-life, which shows no product",
    (domain) => {
      expect(domainIllustration(domain)).toMatch(
        /^\/assets\/images\/mosaic\/[a-z]+-domain-neutral-catalog-3x2\.webp$/,
      );
    },
  );
});
