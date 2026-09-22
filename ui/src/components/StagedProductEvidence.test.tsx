// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StagedProductEvidence } from "./StagedProductEvidence";

const productId = "PARENT0001";
function response() {
  return {
    product: { parent_asin: productId, historical_price_cents: null as number | null, historical_price_min_cents: null as number | null, current_price_cents: null, availability: null },
    evidence: [{ evidence_id: "review-original", parent_asin: productId, variant_asin: "VARIANT001", evidence_type: "customer_review", title: "Source review", text: "The original experience.", source_date: "2021-01-01", verified_purchase: false, rating: 2, helpful_votes: 3 }],
    review_coverage: [{ complete_source_scan: false, selection_policy: "Selected from the scanned source prefix." }],
  };
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("staged source inspection", () => {
  it("keeps missing prices unknown and preserves the review variant and purchase flag", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(response()))));
    render(<StagedProductEvidence productId={productId} />);
    await screen.findByRole("heading", { name: "Evidence from Aurora" });
    expect(screen.getByText(/No price reported/)).toBeTruthy();
    expect(screen.queryByText(/\$0\.00/)).toBeNull();
    expect(screen.getByText(/Purchase not verified in source/)).toBeTruthy();
    expect(screen.getByText(/Reviewed variant: VARIANT001/)).toBeTruthy();
    expect(screen.getByText(/source scan is partial/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Inspect this review’s source" }).getAttribute("href"))
      .toBe("/api/catalog-staging/products/PARENT0001/evidence/review-original");
  });

  it("identifies a reported price as historical and does not invent review coverage", async () => {
    const data = response(); data.product.historical_price_cents = 7999; data.evidence = [];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<StagedProductEvidence productId={productId} />);
    expect(await screen.findByText(/Historical listing price: \$79\.99/)).toBeTruthy();
    expect(screen.getByText(/No review text has been imported/)).toBeTruthy();
  });

  it("rejects evidence belonging to a different product", async () => {
    const data = response(); data.evidence[0].parent_asin = "OTHER00001";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<StagedProductEvidence productId={productId} />);
    expect((await screen.findByRole("alert")).textContent).toContain("does not match this product");
    expect(screen.queryByText("The original experience.")).toBeNull();
  });

  it("keeps starting prices qualified and renders source line breaks without executing markup", async () => {
    const data = response(); data.product.historical_price_min_cents = 599;
    data.evidence[0].text = 'First line.<br />Second line.<img src=x onerror="alert(1)">';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    const { container } = render(<StagedProductEvidence productId={productId} />);
    expect(await screen.findByText(/Historical listing price: from \$5\.99/)).toBeTruthy();
    expect(container.querySelector(".catalog-preview-original")?.textContent)
      .toBe('First line.\nSecond line.<img src=x onerror="alert(1)">');
    expect(container.querySelector("img")).toBeNull();
  });

  it("surfaces a failed source read and lets the user retry the actual request", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response("Unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(response())));
    vi.stubGlobal("fetch", fetch);
    render(<StagedProductEvidence productId={productId} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry source inspection" }));
    await screen.findByRole("heading", { name: "Evidence from Aurora" });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
