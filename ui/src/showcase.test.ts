import { describe, expect, it } from "vitest";
import { showcaseCatalogPage, showcaseProductDetail } from "./showcase";

describe("local Mosaic showcase", () => {
  it("uses the complete local collection when the catalog API is unavailable", () => {
    const page = showcaseCatalogPage({});

    expect(page.total).toBe(10);
    expect(page.products.map((product) => product.image_url)).toEqual(
      expect.arrayContaining([
        "/assets/images/mosaic/melody-go-scene.webp",
        "/assets/images/mosaic/lume-desk-lamp-scene.webp",
        "/assets/images/mosaic/carryall-sleeve.webp",
        "/assets/images/mosaic/flux-wireless-pad-scene.webp",
      ]),
    );
  });

  it("provides the full Mosaic gallery for local product details", () => {
    const product = showcaseProductDetail(17001);

    expect(product?.model).toBe("EchoBud S2");
    expect(product?.media).toHaveLength(4);
    expect(product?.media[0].image_url).toBe("/assets/images/mosaic/echobud-s2.webp");
  });
});
