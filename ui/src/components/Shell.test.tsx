// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CommerceProvider } from "../commerce";
import { Shell } from "./Shell";

describe("Shell navigation", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/catalog");
  });

  afterEach(cleanup);

  it("keeps the participant-facing information architecture to three destinations", () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const navigation = screen.getByRole("navigation");
    expect(
      within(navigation)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Discover", "Shop", "Mosaic Labs"]);
    expect(
      within(navigation).getByRole("link", { name: "Shop" }).getAttribute(
        "aria-current",
      ),
    ).toBe("page");
    expect(
      within(navigation).getByRole("link", { name: "Discover" }).hasAttribute(
        "aria-current",
      ),
    ).toBe(false);
    const menu = screen.getByRole("button", { name: "Open navigation" });
    expect(menu.getAttribute("aria-controls")).toBe(navigation.id);
    expect(screen.queryByRole("link", { name: "Search products" })).toBeNull();
    expect(screen.queryByText("Collections")).toBeNull();
  });

  it("makes the storefront inert while the cart dialog is open", async () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const main = screen.getByText("Shop content").closest("main");
    const header = document.querySelector(".site-header");
    fireEvent.click(screen.getByRole("button", { name: "Bag, 0 items" }));

    const dialog = await screen.findByRole("dialog");
    expect(main?.hasAttribute("inert")).toBe(true);
    expect(main?.getAttribute("aria-hidden")).toBe("true");
    expect(header?.hasAttribute("inert")).toBe(true);
    expect(header?.getAttribute("aria-hidden")).toBe("true");

    fireEvent.click(within(dialog).getByRole("button", { name: "Close bag" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(main?.hasAttribute("inert")).toBe(false);
    expect(header?.hasAttribute("inert")).toBe(false);
  });
});
