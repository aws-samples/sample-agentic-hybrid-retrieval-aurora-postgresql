import { describe, expect, it } from "vitest";
import { showcaseCatalogPage, showcaseProductDetail } from "./showcase";

describe("local Mosaic showcase", () => {
  it("provides the fixed ten-page cohort as 12 unique products per page", () => {
    const page = showcaseCatalogPage({});

    expect(page.total).toBe(120);
    expect(page.limit).toBe(12);
    expect(page.products).toHaveLength(12);

    const products = Array.from(
      { length: 10 },
      (_, index) => showcaseCatalogPage({}, index * 12).products,
    ).flat();
    expect(products).toHaveLength(120);
    expect(new Set(products.map((product) => product.product_id)).size).toBe(120);
  });

  it("points every local product at an installed cohort image", () => {
    const page = showcaseCatalogPage({}, 0, 120);

    for (const product of page.products) {
      expect(product.image_url).toMatch(/^\/assets\/images\/mosaic\//);
    }
  });

  it("honors the current price, rating, category, and availability filter fields", () => {
    const catalog = showcaseCatalogPage({}, 0, 120);
    const category = catalog.facets.category_key[0]?.value;
    const sample = catalog.products.find((product) => product.category_key === category);

    expect(category).toBeTruthy();
    expect(sample).toBeDefined();
    expect(
      showcaseCatalogPage(
        {
          category_key: category,
          min_price_cents: sample!.price_cents,
          min_rating: sample!.rating ?? 0,
          availability: sample!.availability,
        },
        0,
        120,
      ).products,
    ).toContainEqual(expect.objectContaining({ product_id: sample!.product_id }));
  });

  it("uses curated commerce facts instead of synthesized social proof", () => {
    const featured = showcaseCatalogPage({}, 0, 4).products;

    expect(featured[0]).toEqual(expect.objectContaining({
      product_id: 1,
      price_cents: 29900,
      list_price_cents: 32900,
      rating: 4.8,
      review_count: 2431,
      availability: "in_stock",
      inventory_count: 184,
    }));
  });

  it("keeps authoritative USD amounts on the integer-cent API contract", () => {
    const products = showcaseCatalogPage({}, 0, 120).products;

    expect(products).toHaveLength(120);
    for (const product of products) {
      expect(Number.isInteger(product.price_cents)).toBe(true);
      expect(Number.isInteger(product.list_price_cents)).toBe(true);
    }
    expect(showcaseProductDetail(5)).toEqual(expect.objectContaining({
      price_cents: 12995,
      list_price_cents: 15995,
    }));
  });

  it("offers only the verified shot per local product, never a mismatched set", () => {
    const product = showcaseProductDetail(17001);

    expect(product?.model).toBe("EchoBud S2");
    expect(product?.media[0].image_url).toBe("/assets/images/mosaic/echobud-s2.webp");

    // The `-scene`/`-alt`/`-studio` companions were generated in separate passes
    // and depict a different earbud design, so pairing them with this product
    // misattributed the photography. One verified image is the contract.
    expect(product?.media).toHaveLength(1);
    for (const item of product!.media) {
      expect(item.image_url).not.toMatch(/-(scene|alt|studio)\.webp$/);
    }
  });
});
