import { describe, expect, it } from "vitest";
import { domainMedia, productImage, productImageMap } from "./media";
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
    // 52 of the 161 categories in data/dictionaries/taxonomy.json still hold no
    // installed photography and no interchangeable neighbour: a running shoe is
    // not a running top, and nothing in the corpus looks like a monitor arm.
    // Each of these used to resolve to a photograph of one specific product,
    // so a page of studio microphones was illustrated with the Auraluxe H9.
    const empty: Array<[Domain, string, string, string]> = [
      ["consumer_electronics", "studio-microphones", "Audio > Studio Microphones", "ce"],
      ["running_fitness", "running-tops", "Apparel > Running Tops", "rf"],
      ["home_office", "monitor-arms", "Displays > Monitor Arms", "ho"],
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
  /**
   * Installed photography for `over-ear-headphones`: six product-bound cohort
   * shots plus six category plates.
   *
   * Hard-coded rather than derived from the manifests, because a test that reads
   * its own expectation out of the data it is judging cannot fail. When plates
   * land for this category the pool grows and the three tests below go red,
   * which is the signal to raise `exhausting` with it - they only measure the
   * exhaustion behaviour while they draw more rows than the pool holds.
   */
  const headphonePool = 12;
  const exhausting = headphonePool * 2;

  it("gives every card its own photograph while the pool lasts", () => {
    // Hashing cannot do this. Four independent draws from a pool of six repeat
    // a value about a third of the time, and twelve draws from twelve yield
    // about 7.7 distinct values, so a grid always repeated something.
    const rows = Array.from({ length: headphonePool }, (_, index) => filler(100 + index));
    const assigned = productImageMap(rows);
    expect(assigned.size).toBe(headphonePool);
    expect(new Set(assigned.values()).size).toBe(headphonePool);
  });

  it("repeats only after the pool is exhausted", () => {
    const rows = Array.from({ length: exhausting }, (_, index) => filler(200 + index));
    const assigned = productImageMap(rows);
    const inOrder = rows.map((row) => assigned.get(row.product_id));
    // The first page-worth of rows still gets clean photography; the surplus
    // repeats, which is the signal to generate plates.
    expect(new Set(inOrder.slice(0, headphonePool)).size).toBe(headphonePool);
    expect(new Set(inOrder).size).toBe(headphonePool);
  });

  it("spreads an exhausted pool evenly instead of overloading one photograph", () => {
    // Falling back to the hashed choice put four copies of one photograph in a
    // twelve-card grid drawing on a pool of six. Twice as many rows as plates
    // cannot do better than two copies each, and it should not do worse.
    const rows = Array.from({ length: exhausting }, (_, index) => filler(200 + index));
    const counts = new Map<string, number>();
    for (const image of productImageMap(rows).values()) {
      counts.set(image, (counts.get(image) ?? 0) + 1);
    }
    expect(Math.max(...counts.values())).toBe(exhausting / headphonePool);
  });

  it("leaves a product's own photograph on its own card", () => {
    // The flagship shares a pool with the filler rows around it, so an
    // unreserved assignment could hand its photograph to a different product.
    const rows = [
      product({ product_id: 1 }),
      ...Array.from({ length: 5 }, (_, index) => filler(300 + index)),
    ];
    const assigned = productImageMap(rows);
    expect(assigned.get(1)).toBe(
      "/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp",
    );
    expect(new Set(assigned.values()).size).toBe(rows.length);
  });

  it("is stable for the same result set", () => {
    const rows = Array.from({ length: 6 }, (_, index) => filler(400 + index));
    expect([...productImageMap(rows)]).toEqual([...productImageMap(rows)]);
  });
});
