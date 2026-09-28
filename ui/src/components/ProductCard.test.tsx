// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CommerceProvider } from "../commerce";
import { seedRun } from "../retrievalSeed";
import type { ProductSummary } from "../types";
import { ProductCard } from "./ProductCard";

function realListing(historical_price_cents: number | null) {
  return {
    ...seedRun.results[0],
    source_dataset: "reviews-2023-v2",
    price_cents: null,
    historical_price_cents,
  } as ProductSummary;
}

function renderCard(product: ProductSummary) {
  return render(
    <CommerceProvider>
      <ProductCard product={product} variant="catalog" />
    </CommerceProvider>,
  );
}

describe("ProductCard price on a real listing", () => {
  afterEach(cleanup);

  it("labels a recorded price as historical", () => {
    renderCard(realListing(27993));

    expect(screen.getByText("$279.93")).toBeTruthy();
    expect(screen.getByText("Historical listing price")).toBeTruthy();
  });

  it("says the price is not recorded rather than dressing a missing one as a price", () => {
    const { container } = renderCard(realListing(null));

    expect(screen.getByText("Price not recorded")).toBeTruthy();
    expect(screen.queryByText("Historical listing price")).toBeNull();
    expect(container.querySelector(".shop-card-price strong")).toBeNull();
  });
});
