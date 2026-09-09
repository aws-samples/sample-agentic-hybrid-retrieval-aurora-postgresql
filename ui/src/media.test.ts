import { describe, expect, it } from "vitest";
import {
  categoryPoolSize,
  domainMedia,
  productBoundImage,
  productImage,
  productImageMap,
} from "./media";
import type { Domain, ProductSummary } from "./types";

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

/** Above the highest cohort product_id, so these rows carry no bound photograph. */
function filler(product_id: number, overrides: Partial<ProductSummary> = {}) {
  return product({ product_id: 900000 + product_id, ...overrides });
}

describe("productImage", () => {
  it("resolves the exact Sonora catalog photograph from the 200-product manifest", () => {
    expect(productBoundImage(2)).toBe(
      "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    );
  });

  it("preserves a database path into the generated namespace", () => {
    expect(productImage(product({
      product_id: 999999,
      image_url: "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    }))).toBe(
      "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    );
  });

  it("refuses a database path into the scraped substrate", () => {
    // One run of materialize_image_urls.py points 38,750 rows at a photograph
    // of a MacBook on a laptop stand. The category pool must still win.
    expect(productImage(filler(6, {
      domain: "home_office",
      category_key: "electric-standing-desks",
      category_path: "Desks > Electric Standing Desks",
      image_url: "/assets/images/catalog-stand.webp",
    }))).toMatch(/^\/assets\/images\/mosaic\/ho-electric-standing-desks-/);
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

  // These two assert the category the photograph belongs to rather than one
  // filename. Both pools now hold a cohort shot plus a double-figure run of
  // category plates, so which member a single row draws is a property of the
  // hash and the pool order, tested below; the identity of the category is what
  // the historical bug got wrong.
  it("fills a row from its own category, not from a title substring", () => {
    // `/stand/` used to claim every electric standing desk for a laptop riser,
    // so a whole category of desks was illustrated with a MacBook on a stand.
    expect(
      productImage(filler(1, {
        domain: "home_office",
        category_key: "electric-standing-desks",
        category_path: "Desks > Electric Standing Desks",
        title: "WorkLab ESD-200 Electric Standing Desk",
      })),
    ).toMatch(/^\/assets\/images\/mosaic\/ho-electric-standing-desks-/);
  });

  it("fills a category that matched no keyword pattern at all", () => {
    // Mesh Wi-Fi matched none of the old regexes and fell through to the
    // consumer-electronics domain asset, so twelve routers were illustrated
    // with a photograph of headphones.
    expect(
      productImage(filler(2, {
        category_key: "mesh-wi-fi-systems",
        category_path: "Networking > Mesh Wi-Fi Systems",
        title: "NetPulse M6 Mesh Wi-Fi System",
      })),
    ).toMatch(/^\/assets\/images\/mosaic\/ce-mesh-wi-fi-systems-/);
  });

  it("resolves a category whose key is domain-qualified by a collision", () => {
    // Two domains carry a "Portable Monitors" subcategory, so the service emits
    // the fully qualified key for both. Keying pools on the bare subcategory
    // slug alone silently drops the cohort photograph for this category.
    expect(
      productImage(filler(3, {
        category_key: "consumer-electronics-computing-portable-monitors",
        category_path: "Computing > Portable Monitors",
        title: "Vantage P16 Portable Monitor",
      })),
    ).toBe("/assets/images/mosaic/ce-portable-monitors-catalog-3x2.webp");
  });

  it("substitutes a related category only among interchangeable footwear", () => {
    // Trail shoes have no photograph of their own. A road or racing shoe is
    // still a running shoe, so the card reads as catalog breadth.
    expect(
      productImage(filler(4, {
        domain: "running_fitness",
        category_key: "trail-running-shoes",
        category_path: "Footwear > Trail Running Shoes",
      })),
    ).toMatch(/-(road-running-shoes|carbon-racing-shoes|cross-training-shoes)-/);
  });

  it("falls back to a neutral still-life when the category has no photograph", () => {
    // Some categories in data/dictionaries/taxonomy.json still hold no installed
    // photography and no interchangeable neighbour: a running shoe is not a
    // running top, and a desk fan is not a humidifier.
    // Each of these used to resolve to a photograph of one specific product,
    // so a page of studio microphones was illustrated with the Auraluxe H9.
    const empty: Array<[Domain, string, string, string]> = [
      ["consumer_electronics", "studio-microphones", "Audio > Studio Microphones", "ce"],
      ["running_fitness", "running-tops", "Apparel > Running Tops", "rf"],
      ["home_office", "humidifiers", "Air & Environment > Humidifiers", "ho"],
    ];
    for (const [index, [domain, key, path, prefix]] of empty.entries()) {
      expect(
        productImage(filler(500 + index, {
          domain,
          category_key: key,
          category_path: path,
        })),
      ).toBe(`/assets/images/mosaic/${prefix}-domain-neutral-catalog-3x2.webp`);
    }
  });

  it("keeps the product-photograph fallback out of reach in every domain", () => {
    // All three domain-neutral plates are installed, so `domainMedia` is a guard
    // against one being un-installed rather than a live path. Un-install a
    // neutral plate and a whole domain starts illustrating empty categories with
    // a photograph of the Auraluxe H9, the Stride Pro, or the Forma chair again,
    // which is the failure this asserts is unreachable.
    const dishonest = Object.values(domainMedia);
    const domains: Domain[] = ["consumer_electronics", "running_fitness", "home_office"];
    for (const [index, domain] of domains.entries()) {
      const resolved = productImage(filler(600 + index, {
        domain,
        category_key: "no-installed-photography",
        category_path: "Nowhere > Nothing",
      }));
      expect(dishonest).not.toContain(resolved);
      expect(resolved).toMatch(/-domain-neutral-catalog-3x2\.webp$/);
    }
  });
});

describe("productImageMap", () => {
  it("keeps each photo when ranking reverses the result order", () => {
    const rows = Array.from({ length: 42 }, (_, index) => filler(10000 + index));
    expect(productImageMap([...rows].reverse())).toEqual(productImageMap(rows));
  });

  it("keeps Shop photos when Reason selects a smaller shortlist or a single product", () => {
    const rows = Array.from({ length: 42 }, (_, index) => filler(10000 + index));
    const shopImages = productImageMap(rows);
    const picks = rows.filter((_, index) => index % 3 === 0).reverse();
    for (const row of picks) {
      expect(productImageMap(picks).get(row.product_id)).toBe(shopImages.get(row.product_id));
      expect(productImageMap([row]).get(row.product_id)).toBe(shopImages.get(row.product_id));
      expect(productImage(row)).toBe(shopImages.get(row.product_id));
    }
  });

  it("does not change a category photo when a product with its own photo joins the list", () => {
    const rows = Array.from({ length: 42 }, (_, index) => filler(10000 + index));
    const before = productImageMap(rows);
    const after = productImageMap([product({ product_id: 1 }), ...rows]);
    for (const row of rows) {
      expect(after.get(row.product_id)).toBe(before.get(row.product_id));
    }
  });

  it("leaves a product's own photograph on its own card", () => {
    const rows = [
      product({ product_id: 1 }),
      ...Array.from({ length: 5 }, (_, index) => filler(300 + index)),
    ];
    const assigned = productImageMap(rows);
    expect(assigned.get(1)).toBe(
      "/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp",
    );
  });

  it("is stable for the same result set", () => {
    const rows = Array.from({ length: 6 }, (_, index) => filler(400 + index));
    expect([...productImageMap(rows)]).toEqual([...productImageMap(rows)]);
  });
});

/**
 * The pool-size guard, wired to something.
 *
 * `categoryPoolSize` documented itself as the check standing between "a shopper
 * seeing twelve products" and "one photograph twelve times", and nothing called
 * it -- exported, unused, a guard in name only. The failure it describes was
 * live: the Lab 1 anchor query returned twelve rows drawn from six photographs,
 * seven of them the same file, because `acoustic-headphones` had a pool of one.
 */
describe("category photography is deep enough to fill a page", () => {
  // A range of available photos for a Shop page. Stable per-product choices can
  // still repeat; the floor checks catalog variety, not uniqueness in a grid.
  const PAGE = 12;

  // Every category a participant can land on by following the session: the
  // Discover tiles and merchandising doors, plus the categories the three
  // mission queries return. Named rather than derived from the manifests, so
  // this cannot agree with a shrinking pool.
  const REACHABLE: Array<[string, Domain]> = [
    ["over-ear-headphones", "consumer_electronics"],
    ["acoustic-headphones", "home_office"],
    ["quiet-keyboards", "home_office"],
    ["mechanical-keyboards", "home_office"],
    ["ergonomic-office-chairs", "home_office"],
    ["mesh-office-chairs", "home_office"],
    ["executive-chairs", "home_office"],
    ["electric-standing-desks", "home_office"],
    ["charging-docks", "consumer_electronics"],
    ["road-running-shoes", "running_fitness"],
    ["stability-running-shoes", "running_fitness"],
    ["walking-shoes", "running_fitness"],
    ["mobility-tools", "running_fitness"],
  ];

  it.each(REACHABLE)("%s has at least a page of available photos", (categoryKey, domain) => {
    expect(categoryPoolSize(categoryKey, domain)).toBeGreaterThanOrEqual(PAGE);
  });

  /**
   * The gap this guard found on the day it was written, recorded rather than
   * papered over.
   *
   * `true-wireless-earbuds` is the catalog's third-largest category (13,000
   * products) and Discover leads with an EchoBud S2 card, but it has no plate
   * set: eleven exact shots, one short of a page. It gets no `relatedCategories`
   * row because it has no interchangeable neighbour -- an earbud is not an
   * over-ear headphone, and pretending otherwise is the mistake that list
   * exists to prevent. The fix is a plate run for the category. Generating
   * plates will turn this assertion red, which is the signal to move the key up
   * into REACHABLE above.
   */
  it("records true-wireless-earbuds as still short of a page", () => {
    expect(categoryPoolSize("true-wireless-earbuds", "consumer_electronics")).toBe(11);
  });

  it("names a category that is genuinely starved, so the floor is load-bearing", () => {
    // Witness. Every assertion above would pass on a codebase where every pool
    // were enormous, and prove nothing about the floor. A category with neither
    // plates nor exact shots is still one photograph for every row.
    expect(categoryPoolSize("desk-fans", "home_office")).toBeLessThan(PAGE);
  });
});
