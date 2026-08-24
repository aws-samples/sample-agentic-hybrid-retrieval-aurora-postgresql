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
        .map((link) => link.getAttribute("href")),
    ).toEqual(["/", "/catalog", "/labs/retrieval"]);
    // No query on Shop, so nothing is carried and the Playground link is plain.
    // Discover | Shop | Playground, and nothing else. The third entry printed
    // "Observatory" with an "Optional" badge welded to it, which is a fourth name
    // for the surface and an instruction to skip it.
    expect(
      within(navigation).getAllByRole("link").map((link) => link.textContent),
    ).toEqual(["Discover", "Shop", "Playground"]);
    expect(navigation.textContent).not.toMatch(/Observatory|Optional|Mosaic Labs/);
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
    expect(screen.queryByRole("button", { name: "Account" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Search the catalog" })).toBeNull();
    expect(screen.queryByText("Collections")).toBeNull();
  });

  it("carries an active Shop query onto the Playground entry", () => {
    // Otherwise a participant who searched and then reached for the header arrived
    // at a Playground about a different query. The only other hand-off is a link
    // inside Shop's collapsed "Why these results" disclosure.
    window.history.replaceState(
      {},
      "",
      "/catalog?q=wirless+noice+canceling+hedphones&domain=consumer_electronics&in_stock_only=true",
    );
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const href = within(screen.getByRole("navigation"))
      .getByRole("link", { name: "Playground" })
      .getAttribute("href")!;
    const params = new URLSearchParams(href.split("?")[1]);

    expect(href.startsWith("/labs/retrieval?")).toBe(true);
    expect(params.get("q")).toBe("wirless noice canceling hedphones");
    expect(params.get("domain")).toBe("consumer_electronics");
    expect(params.get("in_stock_only")).toBe("true");
  });

  it("carries nothing from a surface that has no query", () => {
    window.history.replaceState({}, "", "/labs/retrieval");
    render(
      <CommerceProvider>
        <Shell>
          <div>Playground content</div>
        </Shell>
      </CommerceProvider>,
    );

    expect(
      within(screen.getByRole("navigation"))
        .getByRole("link", { name: "Playground" })
        .getAttribute("href"),
    ).toBe("/labs/retrieval");
  });

  it("closes the storefront with a footer that borrows no card brand", () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const footer = screen.getByRole("contentinfo");
    expect(
      within(footer)
        .getByRole("list", { name: "Payment methods" })
        .textContent,
    ).toBe(
      "Credit and debitContactlessDigital walletBank transfer",
    );
    // A card network's mark is a trademark licensed to merchants who accept that
    // card, and this catalog accepts nothing. Naming one here would assert a
    // commercial relationship that does not exist, in a public sample repository.
    // The families are generic on purpose; this is what stops a later "make the
    // footer look real" pass from quietly reintroducing the marks.
    expect(footer.textContent).not.toMatch(
      /visa|mastercard|maestro|amex|american express|discover card|paypal|apple pay|google pay|klarna|afterpay/i,
    );
    // A storefront that prints prices, stock, reviews and then payment methods has
    // to say that none of it is real. Everything else on the page is built to be
    // believed, which is exactly why this line cannot go missing.
    expect(footer.textContent).toContain("Nothing here charges a card");
    expect(footer.textContent).toContain("synthetic data");
  });

  it("leaves the footer off the instrument surfaces", () => {
    // The Playground ends in a measurement, not an invitation to buy. A
    // payment-methods band under a query plan would be the one incoherent thing
    // on it.
    window.history.replaceState({}, "", "/labs/retrieval");
    render(
      <CommerceProvider>
        <Shell>
          <div>Playground content</div>
        </Shell>
      </CommerceProvider>,
    );

    expect(screen.queryByRole("contentinfo")).toBeNull();
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
    const footer = document.querySelector(".site-footer");
    expect(footer?.hasAttribute("inert")).toBe(true);
    expect(footer?.getAttribute("aria-hidden")).toBe("true");

    fireEvent.click(within(dialog).getByRole("button", { name: "Close bag" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(main?.hasAttribute("inert")).toBe(false);
    expect(header?.hasAttribute("inert")).toBe(false);
    expect(footer?.hasAttribute("inert")).toBe(false);
  });
});
