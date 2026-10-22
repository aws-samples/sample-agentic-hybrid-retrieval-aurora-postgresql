// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

  it("shows a recorded price with the historical-price tooltip, not a caption", () => {
    renderCard(realListing(27993));

    expect(screen.getByText("$279.93").getAttribute("title")).toBe("Historical price from the original listing");
    expect(screen.queryByText("Historical price")).toBeNull();
  });

  it("shows an en dash with a tooltip rather than dressing a missing price as one", () => {
    renderCard(realListing(null));

    const none = screen.getByLabelText("Price not recorded");
    expect(none.textContent).toBe("–");
    expect(none.getAttribute("title")).toMatch(/No price recorded/);
    expect(screen.queryByText("Price not recorded")).toBeNull();
  });
});

describe("ProductCard ranking chips and wanted marking", () => {
  afterEach(cleanup);

  function ranked(product: ProductSummary, wanted?: Parameters<typeof ProductCard>[0]["wanted"]) {
    return render(
      <CommerceProvider>
        <ProductCard product={product} variant="catalog" showSignals wanted={wanted} />
      </CommerceProvider>,
    );
  }

  it("prints the product's path: the searches that found it, then combined and final", () => {
    const product = structuredClone(seedRun.results[0]);
    product.signals!.fts = { rank: 3, raw_score: 1, rrf_contribution: 0.01 };
    product.signals!.trigram = { rank: null, raw_score: null, rrf_contribution: null };
    product.signals!.semantic = { rank: 10, raw_score: 1, rrf_contribution: 0.01 };
    product.signals!.pre_rerank_rank = 21;
    product.signals!.final_rank = 5;
    ranked(product);
    // A search that missed is left out of the path, not printed as a rank.
    expect(screen.getByLabelText("Found by").textContent).toBe("Full-text #3 + Semantic #10");
    const position = screen.getByText("Final #5").parentElement!;
    expect(position.textContent).toContain("Combined #21 →");
    expect(position.querySelector(".rank-move")?.getAttribute("data-move")).toBe("up");
  });

  it("leaves the path out for a product no search ranked", () => {
    const product = structuredClone(seedRun.results[0]);
    const missed = { rank: null, raw_score: null, rrf_contribution: null };
    product.signals = { ...product.signals!, fts: missed, trigram: missed, semantic: missed };
    ranked(product);
    expect(screen.queryByLabelText("Found by")).toBeNull();
  });

  it("marks the wanted product with its live position and tier", () => {
    const product = structuredClone(seedRun.results[0]);
    const { container } = ranked(product, { productId: product.product_id, tier: "target", finalRank: 5 });
    expect(container.querySelector("[data-wanted='target']")).toBeTruthy();
    expect(screen.getByText("Wanted · final #5").getAttribute("data-tier")).toBe("target");
  });

  it("leaves an ordinary card unmarked and keeps one accessible name for the receipt", () => {
    const { container } = ranked(structuredClone(seedRun.results[0]));
    expect(container.querySelector("[data-wanted]")).toBeNull();
    expect(screen.queryByText(/^Wanted/)).toBeNull();
    const summary = screen.getByText("Why this match");
    expect(summary.getAttribute("aria-label")).toBeNull();
    fireEvent.click(summary);
  });
});
