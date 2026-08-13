// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  calculateOrderSummary,
  CommerceProvider,
  type CartLine,
  useCommerce,
} from "./commerce";
import { ProductCard } from "./components/ProductCard";
import type { ProductSummary } from "./types";

const product: ProductSummary = {
  product_id: 101,
  sku: "MOS-101",
  title: "Mosaic Studio One",
  short_description: "A premium test product.",
  domain: "consumer_electronics",
  category_key: "over-ear-headphones",
  category_path: "Audio > Over-Ear Headphones",
  brand: "Mosaic",
  model: "Studio One",
  price_cents: 10000,
  list_price_cents: 12000,
  currency: "USD",
  rating: 4.8,
  review_count: 248,
  availability: "in_stock",
  inventory_count: 4,
  attributes: {},
  tags: [],
  catalog_asset_key: null,
  canonical_group_id: null,
  media_tier: "premium",
  is_flagship: true,
  is_retrieval_anchor: false,
  image_url: "/assets/images/mosaic/auraluxe-h9.webp",
  image_source: "test",
  signals: null,
  sources: [],
};

function CardHarness() {
  const { isCartOpen, itemCount, isFavorite } = useCommerce();
  return (
    <>
      <ProductCard product={product} variant="catalog" />
      <output aria-label="Cart item count">{itemCount}</output>
      <output aria-label="Cart drawer status">
        {isCartOpen ? "open" : "closed"}
      </output>
      <output aria-label="Favorite status">
        {isFavorite(product.product_id) ? "saved" : "not saved"}
      </output>
    </>
  );
}

describe("commerce", () => {
  afterEach(cleanup);

  it("calculates shipping and tax in cents", () => {
    const lines: CartLine[] = [{ product, quantity: 1 }];

    expect(calculateOrderSummary(lines)).toEqual({
      subtotal: 10000,
      shipping: 0,
      tax: 825,
      total: 10825,
    });
    expect(calculateOrderSummary(lines, "express")).toEqual({
      subtotal: 10000,
      shipping: 1695,
      tax: 825,
      total: 12520,
    });
  });

  it("shares favorite and cart state with a catalog card", () => {
    render(
      <CommerceProvider>
        <CardHarness />
      </CommerceProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: `Save ${product.title}` }),
    );
    expect(screen.getByLabelText("Favorite status").textContent).toBe("saved");

    fireEvent.click(
      screen.getByRole("button", { name: `Add ${product.title} to cart` }),
    );
    expect(screen.getByLabelText("Cart item count").textContent).toBe("1");
    expect(screen.getByLabelText("Cart drawer status").textContent).toBe("open");
    expect(
      screen.getByRole("button", { name: `Add another ${product.title} to cart` }),
    ).toBeTruthy();
    expect(document.querySelector(".cart-flight")).toBeNull();
  });
});
