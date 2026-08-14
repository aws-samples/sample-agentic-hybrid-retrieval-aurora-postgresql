// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  calculateOrderSummary,
  cartQuantityLimit,
  CommerceProvider,
  type CartLine,
  useCommerce,
} from "./commerce";
import { ProductCard } from "./components/ProductCard";
import { CommerceDrawer } from "./components/CommerceDrawer";
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
  const { isCartOpen, itemCount, isFavorite, openCart } = useCommerce();
  return (
    <>
      <ProductCard product={product} variant="catalog" />
      <CommerceDrawer />
      <button type="button" onClick={openCart}>Open bag</button>
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
  afterEach(() => {
    cleanup();
    try {
      window.localStorage.clear();
    } catch {
      // The test runtime may intentionally omit persistent browser storage.
    }
  });

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

    const belowThreshold = [{ product: { ...product, price_cents: 5000 }, quantity: 1 }];
    expect(calculateOrderSummary(belowThreshold)).toEqual({
      subtotal: 5000,
      shipping: 895,
      tax: 413,
      total: 6308,
    });
  });

  it("uses availability and inventory as the cart quantity boundary", () => {
    expect(cartQuantityLimit({ ...product, inventory_count: 2 })).toBe(2);
    expect(cartQuantityLimit({ ...product, inventory_count: 20 })).toBe(9);
    expect(
      cartQuantityLimit({
        ...product,
        availability: "out_of_stock",
        inventory_count: 20,
      }),
    ).toBe(0);
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

  it("does not add beyond the loaded inventory", () => {
    const scarceProduct = { ...product, inventory_count: 2 };

    render(
      <CommerceProvider>
        <ProductCard product={scarceProduct} variant="catalog" />
        <CommerceDrawer />
        <CartCount />
      </CommerceProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: `Add ${product.title} to cart` }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: `Add another ${product.title} to cart` }),
    );

    expect(screen.getByLabelText("Cart item count").textContent).toBe("2");
    expect(
      (
        screen.getByRole("button", {
          name: `${product.title} quantity limit reached`,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: `Increase ${product.title} quantity`,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);

    const decrease = screen.getByRole("button", {
      name: `Decrease ${product.title} quantity`,
    }) as HTMLButtonElement;
    expect(decrease.disabled).toBe(false);
    fireEvent.click(decrease);
    expect(screen.getByLabelText("Cart item count").textContent).toBe("1");
    expect(decrease.disabled).toBe(true);
  });

  it("contains keyboard focus and restores it after the bag closes", async () => {
    render(
      <CommerceProvider>
        <CardHarness />
      </CommerceProvider>,
    );

    const add = screen.getByRole("button", { name: `Add ${product.title} to cart` });
    add.focus();
    fireEvent.click(add);

    const dialog = await screen.findByRole("dialog", { name: /your bag/i });
    const close = within(dialog).getByRole("button", { name: "Close bag" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /checkout/i }),
    );

    fireEvent.click(close);
    await waitFor(() => expect(dialog.isConnected).toBe(false));
    expect(document.activeElement).toBe(add);
  });

  it("completes the demo checkout, clears the bag, and reopens cleanly", async () => {
    render(
      <CommerceProvider>
        <CardHarness />
      </CommerceProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: `Add ${product.title} to cart` }),
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));

    const deliveryHeading = await screen.findByRole("heading", {
      name: "Delivery details",
    });
    await waitFor(() => expect(document.activeElement).toBe(deliveryHeading));

    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "shopper@example.com" },
    });
    fireEvent.change(screen.getByLabelText("First name"), {
      target: { value: "Avery" },
    });
    fireEvent.change(screen.getByLabelText("Last name"), {
      target: { value: "Morgan" },
    });
    fireEvent.change(screen.getByLabelText("Address"), {
      target: { value: "410 Mosaic Way" },
    });
    fireEvent.change(screen.getByLabelText("City"), {
      target: { value: "Seattle" },
    });
    fireEvent.change(screen.getByLabelText("State"), {
      target: { value: "wa" },
    });
    fireEvent.change(screen.getByLabelText("ZIP"), {
      target: { value: "98101" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    const paymentHeading = await screen.findByRole("heading", { name: "Payment" });
    await waitFor(() => expect(document.activeElement).toBe(paymentHeading));

    fireEvent.click(screen.getByRole("button", { name: "Review order" }));
    const reviewHeading = await screen.findByRole("heading", { name: "Review order" });
    await waitFor(() => expect(document.activeElement).toBe(reviewHeading));
    expect(screen.getByText(/shopper@example.com/).textContent).toContain(
      "Seattle, WA 98101",
    );

    fireEvent.click(screen.getByRole("button", { name: /place demo order/i }));
    expect(
      await screen.findByRole("heading", { name: "Order confirmed" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Cart item count").textContent).toBe("0");

    const confirmation = screen.getByRole("dialog", { name: "Order confirmed" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Close bag" }));
    fireEvent.click(screen.getByRole("button", { name: "Open bag" }));
    expect(
      await screen.findByRole("heading", { name: "Your bag (0)" }),
    ).toBeTruthy();
    expect(screen.getByText("Your bag is empty")).toBeTruthy();
  });

  it("returns to the bag after checkout is closed mid-flow", async () => {
    render(
      <CommerceProvider>
        <CardHarness />
      </CommerceProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: `Add ${product.title} to cart` }),
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));
    const deliveryHeading = await screen.findByRole("heading", {
      name: "Delivery details",
    });
    const checkoutDialog = deliveryHeading.closest<HTMLElement>('[role="dialog"]');
    if (!checkoutDialog) throw new Error("Checkout dialog was not rendered");

    fireEvent.click(
      within(checkoutDialog).getByRole("button", { name: "Close bag" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(
      screen.getByRole("button", { name: `Add another ${product.title} to cart` }),
    );
    expect(
      await screen.findByRole("heading", { name: "Your bag (2)" }),
    ).toBeTruthy();
  });
});

function CartCount() {
  const { itemCount } = useCommerce();
  return <output aria-label="Cart item count">{itemCount}</output>;
}
