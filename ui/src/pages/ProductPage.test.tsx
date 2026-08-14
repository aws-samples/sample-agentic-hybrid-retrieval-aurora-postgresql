// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage, showcaseProductDetail } from "../showcase";
import type { ProductDetail } from "../types";
import { ProductPage } from "./ProductPage";

vi.mock("../api", () => ({
  api: {
    catalog: vi.fn(),
    product: vi.fn(),
  },
}));

type DeferredProduct = {
  promise: Promise<ProductDetail>;
  resolve: (product: ProductDetail) => void;
};

function deferredProduct(): DeferredProduct {
  let resolve!: (product: ProductDetail) => void;
  const promise = new Promise<ProductDetail>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("ProductPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/products/1");
    vi.mocked(api.product).mockReset();
    vi.mocked(api.catalog).mockReset();
    vi.mocked(api.catalog).mockResolvedValue(showcaseCatalogPage({}, 0, 5));
  });

  afterEach(cleanup);

  it("ignores an older product response after the route changes", async () => {
    const first = deferredProduct();
    const second = deferredProduct();
    vi.mocked(api.product).mockImplementation((productId) => (
      productId === 1 ? first.promise : second.promise
    ));

    render(
      <CommerceProvider>
        <ProductPage />
      </CommerceProvider>,
    );

    await waitFor(() => expect(api.product).toHaveBeenCalledWith(1));
    window.history.pushState({}, "", "/products/17001");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(api.product).toHaveBeenCalledWith(17001));

    const echoBud = showcaseProductDetail(17001);
    const auraluxe = showcaseProductDetail(1);
    if (!echoBud || !auraluxe) throw new Error("Missing product race fixtures");

    await act(async () => {
      second.resolve(echoBud);
      await second.promise;
    });
    expect(
      await screen.findByRole("heading", { name: "Mosaic EchoBud S2" }),
    ).toBeTruthy();

    await act(async () => {
      first.resolve(auraluxe);
      await first.promise;
    });
    expect(
      screen.getByRole("heading", { name: "Mosaic EchoBud S2" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Mosaic Auraluxe H9" }),
    ).toBeNull();
  });
});
