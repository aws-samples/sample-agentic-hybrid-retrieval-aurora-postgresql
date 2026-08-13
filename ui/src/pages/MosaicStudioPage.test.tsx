// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { showcaseProductDetail } from "../showcase";
import { MosaicStudioPage } from "./MosaicStudioPage";

vi.mock("../api", () => ({
  api: {
    product: vi.fn(),
  },
}));

const chair = showcaseProductDetail(370001)!;
const display = showcaseProductDetail(420001)!;
const keyboard = {
  ...chair,
  product_id: 429001,
  title: "Keysmith MX Quiet Mechanical Wireless Keyboard",
  model: "MX Quiet",
  brand: "Keysmith",
  sku: "KEY-MX-QUIET",
  category_key: "quiet-keyboards",
  category_path: "Workspace > Input Devices > Quiet Keyboards",
  price_cents: 16999,
  short_description: "Quiet mechanical input for focused work.",
  long_description: "A quiet mechanical keyboard for long, focused workdays.",
  attributes: { quiet_typing: true, wireless: true },
};

describe("MosaicStudioPage", () => {
  beforeEach(() => {
    vi.mocked(api.product).mockReset();
    vi.mocked(api.product).mockImplementation(async (productId) => {
      const product = new Map([
        [370001, chair],
        [420001, display],
        [429001, keyboard],
      ]).get(productId);
      if (!product) throw new Error(`Unexpected studio product ${productId}`);
      return product;
    });
  });

  afterEach(cleanup);

  it("keeps Studio outside the required Labs path and hands off to Shop", async () => {
    render(<MosaicStudioPage />);

    expect(screen.getByRole("link", { name: "Workshop" }).getAttribute("href")).toBe(
      "/mosaic-labs",
    );
    expect(screen.getByRole("link", { name: "Studio" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(
      screen.getByText(/It is a selected composition, not a generated recommendation\./),
    ).toBeTruthy();

    await waitFor(() => {
      expect(api.product).toHaveBeenCalledTimes(3);
    });

    fireEvent.click(screen.getByRole("button", { name: "Assemble the studio" }));

    expect(screen.getByRole("link", { name: /Forma Ergonomic/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Atelier 32/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /MX Quiet/ })).toBeTruthy();
    expect(screen.getByText("Studio assembled")).toBeTruthy();

    const workspace = screen.getByRole("link", { name: "Shop the workspace" });
    expect(workspace.getAttribute("href")).toBe("/catalog?domain=home_office");
  });

  it("does not fabricate products when Aurora records cannot load", async () => {
    vi.mocked(api.product).mockRejectedValue(new Error("Aurora is unavailable"));
    render(<MosaicStudioPage />);

    expect(
      await screen.findByText("Studio pieces are unavailable."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Assemble the studio" })).toBeNull();
  });
});
