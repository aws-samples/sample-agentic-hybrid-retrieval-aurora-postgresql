import type { CatalogPage, ProductDetail, SearchFilters } from "./types";

/** Small component-test inputs, independent of any deployed catalog. */
export function fixtureProductDetail(productId: number): ProductDetail {
  const kind = productId === 17001 ? "earbuds" : productId === 370001 ? "chair" : productId === 420001 ? "monitor" : "headphones";
  const title = `Test ${kind} ${productId}`;
  const category = kind === "headphones" ? "over-ear-headphones" : kind === "chair" ? "desk-chairs" : kind === "monitor" ? "monitors" : "earbuds";
  return {
    product_id: productId, sku: `TEST-${productId}`, title,
    short_description: `Component test ${kind}.`, long_description: `Component test details for ${kind}.`,
    domain: kind === "chair" ? "home_office" : "consumer_electronics",
    category_key: category, category_path: category, brand: "Test", model: `${kind} ${productId}`,
    price_cents: 12900, list_price_cents: 14900, currency: "USD", rating: 4.5, review_count: 12,
    availability: "in_stock", inventory_count: 10, attributes: {}, tags: [],
    catalog_asset_key: null, canonical_group_id: `test-${productId}`, media_tier: null,
    is_flagship: false, is_retrieval_anchor: false, image_url: null, image_source: null,
    signals: null, sources: [{ source_uri: `mosaic://test/${productId}`, revision: "test", title, quote: `Component test ${kind}.` }],
    source_system: "component-test", updated_at: "2026-01-01T00:00:00Z", media: [], reviews: [],
  };
}

export function fixtureCatalogPage(_filters: SearchFilters, offset = 0, limit = 12): CatalogPage {
  const products = [1, 17001, 370001, 420001, 2, 3, 4, 5, 6, 7, 8, 9].map(fixtureProductDetail);
  return { total: products.length, offset, limit, products: products.slice(offset, offset + limit), facets: { brand: [{ value: "Test", count: products.length }] } };
}
