// @vitest-environment jsdom

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import type { ProductDetail } from "../types";
import { ProductDrawer } from "./ProductDrawer";

vi.mock("../api", () => ({
  api: {
    product: vi.fn(),
  },
}));

const product: ProductDetail = {
  product_id: 101,
  sku: "MOSAIC-101",
  title: "Mosaic QuietType K2",
  short_description: "A quiet keyboard for shared workspaces.",
  long_description: "A quiet keyboard measured for shared workspaces.",
  domain: "home_office",
  category_key: "keyboards",
  category_path: "Home Office > Keyboards",
  brand: "Mosaic",
  model: "QuietType K2",
  price_cents: 12900,
  list_price_cents: 14900,
  currency: "USD",
  rating: 4.7,
  review_count: 18,
  availability: "in_stock",
  inventory_count: 8,
  attributes: {},
  tags: [],
  catalog_asset_key: null,
  canonical_group_id: "quiettype-k2",
  media_tier: null,
  is_flagship: false,
  is_retrieval_anchor: true,
  image_url: null,
  image_source: null,
  signals: null,
  sources: [],
  source_system: "mosaic_catalog",
  updated_at: "2026-08-01T00:00:00Z",
  media: [],
  reviews: [],
};

function renderDrawer() {
  return render(
    <CommerceProvider>
      <ProductDrawer
        productId={product.product_id}
        imageByProductId={new Map()}
        onClose={vi.fn()}
      />
    </CommerceProvider>,
  );
}

describe("ProductDrawer request status", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("announces loading and marks the dialog busy", () => {
    vi.mocked(api.product).mockReturnValue(new Promise(() => {}));
    renderDrawer();

    const dialog = screen.getByRole("dialog", { name: "Product details" });
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    expect(within(dialog).getByRole("status").textContent)
      .toContain("Pulling the full catalog row");
  });

  it("announces a failed product request as an alert", async () => {
    vi.mocked(api.product).mockRejectedValue(new Error("Catalog row unavailable"));
    renderDrawer();

    const dialog = screen.getByRole("dialog", { name: "Product details" });
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("Catalog row unavailable");
    expect(dialog.getAttribute("aria-busy")).toBe("false");
  });

  it("announces successful completion", async () => {
    vi.mocked(api.product).mockResolvedValue(product);
    renderDrawer();

    const dialog = screen.getByRole("dialog", { name: "Product details" });
    await waitFor(() => {
      expect(within(dialog).getByRole("status").textContent)
        .toContain(`Product details loaded for ${product.title}`);
    });
    expect(dialog.getAttribute("aria-busy")).toBe("false");
  });
});
