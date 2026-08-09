import { describe, expect, it } from "vitest";
import { showcaseCatalogPage, showcaseProductDetail } from "./showcase";

describe("local Mosaic showcase", () => {
  it("fills at least two full catalog pages so the 3x4 grid has no short row", () => {
    const page = showcaseCatalogPage({});

    // Asserting a floor rather than an exact count: the seed grows as cohort
    // photography lands, and a test that pins the number would fail on every
    // addition without telling us anything about the grid.
    expect(page.total).toBeGreaterThanOrEqual(24);
    expect(page.total % 12).toBe(0);
    expect(new Set(page.products.map((product) => product.product_id)).size).toBe(
      page.products.length,
    );
  });

  it("points every local product at an installed cohort image", () => {
    const page = showcaseCatalogPage({});

    for (const product of page.products) {
      expect(product.image_url).toMatch(/^\/assets\/images\/mosaic\//);
    }
  });

  it("honors the current price, rating, category, and availability filter fields", () => {
    const catalog = showcaseCatalogPage({});
    const category = catalog.facets.category_key[0]?.value;
    const sample = catalog.products.find((product) => product.category_key === category);

    expect(category).toBeTruthy();
    expect(sample).toBeDefined();
    expect(
      showcaseCatalogPage({
        category_key: category,
        min_price_cents: sample!.price_cents,
        min_rating: sample!.rating ?? 0,
        availability: sample!.availability,
      }).products,
    ).toContainEqual(expect.objectContaining({ product_id: sample!.product_id }));
  });

  it("provides the full Mosaic gallery for local product details", () => {
    const product = showcaseProductDetail(17001);

    expect(product?.model).toBe("EchoBud S2");
    expect(product?.media).toHaveLength(4);
    expect(product?.media[0].image_url).toBe("/assets/images/mosaic/echobud-s2.webp");
  });
});
