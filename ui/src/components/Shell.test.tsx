// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import type { HealthResponse, LabStateResponse } from "../types";
import { Shell } from "./Shell";

vi.mock("../api", () => ({
  api: {
    health: vi.fn(),
    labsState: vi.fn(),
  },
}));

function healthFixture(codeEditorUrl: string | null): HealthResponse {
  return {
    status: "ok",
    service: "catalog-hybrid-retrieval",
    models: {
      embedding: "cohere.embed-v4:0",
      rerank: "cohere.rerank-v3-5:0",
      agent: "anthropic.claude-sonnet-4-6",
      synthesis: "anthropic.claude-sonnet-4-6",
    },
    code_editor_url: codeEditorUrl,
  };
}

const labsFixture: LabStateResponse = {
  labs: [
    {
      lab_id: 1,
      source_state: "broken",
      database_state: "stale",
      detail: "The trigram CTE is still commented out.",
    },
    {
      lab_id: 2,
      source_state: "solved",
      database_state: "applied",
      detail: "The reciprocal-rank formula is restored and applied.",
    },
    {
      lab_id: 3,
      source_state: "solved",
      database_state: "not_applicable",
      detail: "Lab 3's seam lives in the API process.",
    },
  ],
};

describe("Shell navigation", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/catalog");
    vi.mocked(api.health).mockReset();
    vi.mocked(api.labsState).mockReset();
    // Left pending by default, which keeps the synchronous tests act()-clean.
    // The tests that assert on the header's lab state resolve them themselves.
    vi.mocked(api.health).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.labsState).mockReturnValue(new Promise(() => {}));
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

    // By name: the footer carries a second navigation landmark, and this test is
    // about the header's three destinations.
    const navigation = screen.getByRole("navigation", { name: "Storefront" });
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

  it("provides a keyboard bypass target for the persistent storefront chrome", () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const skip = screen.getByRole("link", { name: "Skip to main content" });
    const main = screen.getByText("Shop content").closest("main");
    expect(skip.getAttribute("href")).toBe("#main-content");
    expect(main?.id).toBe("main-content");
    expect(main?.getAttribute("tabindex")).toBe("-1");
  });

  it("moves focus into the opened menu and restores it on Escape", async () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const menu = screen.getByRole("button", { name: "Open navigation" });
    const navigation = screen.getByRole("navigation", { name: "Storefront" });
    fireEvent.click(menu);

    await waitFor(() => {
      expect(document.activeElement).toBe(
        within(navigation).getByRole("link", { name: "Discover" }),
      );
    });
    expect(menu.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Open navigation" })).toBe(menu);
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(menu);
  });

  it("carries an active Shop query onto the Playground entry", () => {
    // Otherwise a participant who searched and then reached for the header arrived
    // at a Playground about a different query. The only other hand-off is a link
    // inside Shop's collapsed "Why these results" disclosure.
    window.history.replaceState(
      {},
      "",
      "/catalog?q=noice+cancelng+hedfones&domain=consumer_electronics&in_stock_only=true",
    );
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const href = within(screen.getByRole("navigation", { name: "Storefront" }))
      .getByRole("link", { name: "Playground" })
      .getAttribute("href")!;
    const params = new URLSearchParams(href.split("?")[1]);

    expect(href.startsWith("/labs/retrieval?")).toBe(true);
    expect(params.get("q")).toBe("noice cancelng hedfones");
    expect(params.get("domain")).toBe("consumer_electronics");
    expect(params.get("in_stock_only")).toBe("true");
    // Shop has not recorded a run on this URL, so there is no event to carry and
    // the header does not invent one.
    expect(params.get("event")).toBeNull();
  });

  it("carries the Shop run's own event id onto the Playground entry", () => {
    // The header is the second hand-off path, and it has to preserve the run the
    // shopper was actually shown for the same reason the in-page link does: a
    // Playground that re-runs the query mints a different event, and the run
    // behind the results on screen becomes unreachable.
    window.history.replaceState(
      {},
      "",
      "/catalog?q=noice+cancelng+hedfones&event=9614ed9b-4ceb-4aad-9276-4e69af2231b9",
    );
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const href = within(screen.getByRole("navigation", { name: "Storefront" }))
      .getByRole("link", { name: "Playground" })
      .getAttribute("href")!;
    const params = new URLSearchParams(href.split("?")[1]);

    expect(params.get("q")).toBe("noice cancelng hedfones");
    expect(params.get("event")).toBe("9614ed9b-4ceb-4aad-9276-4e69af2231b9");
  });

  it("carries no event id that is not shaped like one", () => {
    window.history.replaceState({}, "", "/catalog?q=quiet+keyboard&event=not-an-event");
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const href = within(screen.getByRole("navigation", { name: "Storefront" }))
      .getByRole("link", { name: "Playground" })
      .getAttribute("href")!;

    expect(href).not.toContain("event=");
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
      within(screen.getByRole("navigation", { name: "Storefront" }))
        .getByRole("link", { name: "Playground" })
        .getAttribute("href"),
    ).toBe("/labs/retrieval");
  });

  it("hides the Code Editor button when the service reports no Code Editor", async () => {
    // A workshop image without a Code Editor is a real deployment, not a fault.
    // A dead button pointing nowhere would be the fault.
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    await waitFor(() => expect(screen.getByText("source: broken")).toBeTruthy());
    expect(screen.queryByRole("link", { name: "Code Editor" })).toBeNull();
  });

  it("opens the Code Editor in a new tab when the service publishes one", async () => {
    vi.mocked(api.health).mockResolvedValue(
      healthFixture("https://code.mosaic-workshop.example"),
    );
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const link = await screen.findByRole("link", { name: "Code Editor" });
    expect(link.getAttribute("href")).toBe("https://code.mosaic-workshop.example");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    // The header's three destinations are unchanged: the Code Editor is an
    // action beside the bag, not a fourth place to be.
    expect(
      within(screen.getByRole("navigation", { name: "Storefront" }))
        .getAllByRole("link")
        .map((entry) => entry.textContent),
    ).toEqual(["Discover", "Shop", "Playground"]);
  });

  it("reports Lab 1 by default, in both the places a lab can be broken", async () => {
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const state = await screen.findByRole("group", { name: "Lab 1 state" });
    // Two chips, not one verdict. An edited file in front of an unapplied
    // cluster is the most common way a repair looks finished and is not, and
    // collapsing the two states would hide exactly that.
    expect(state.textContent).toBe("source: brokendatabase: stale");
  });

  it("follows the lab named on the URL, by mission and by example", async () => {
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    window.history.replaceState({}, "", "/catalog?mission=rank-with-evidence");
    const { unmount } = render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    expect(
      (await screen.findByRole("group", { name: "Lab 2 state" })).textContent,
    ).toBe("source: solveddatabase: applied");
    unmount();

    window.history.replaceState({}, "", "/labs/retrieval?example=agentic-research");
    render(
      <CommerceProvider>
        <Shell>
          <div>Playground content</div>
        </Shell>
      </CommerceProvider>,
    );

    // Lab 3's seam lives in the API process, so there is no schema to re-apply
    // and the chip says so rather than printing a stale-looking verdict.
    expect(
      (await screen.findByRole("group", { name: "Lab 3 state" })).textContent,
    ).toBe("source: solveddatabase: not applicable");
  });

  it("re-reads the lab state when Shop records a new run", async () => {
    // Shop's callout flips to `Repair verified` the moment a re-run comes back
    // repaired. The header used to keep printing `source: broken` beside it
    // until the page was reloaded, which is the workshop contradicting itself
    // on one screen. The run Shop records on its own URL is the signal.
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    window.history.replaceState(
      {},
      "",
      "/catalog?q=noice+cancelng+hedfones&event=9614ed9b-4ceb-4aad-9276-4e69af2231b9",
    );
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    expect(
      (await screen.findByRole("group", { name: "Lab 1 state" })).textContent,
    ).toBe("source: brokendatabase: stale");
    expect(vi.mocked(api.labsState)).toHaveBeenCalledTimes(1);

    vi.mocked(api.labsState).mockResolvedValue({
      labs: [
        { ...labsFixture.labs[0], source_state: "solved", database_state: "applied" },
        ...labsFixture.labs.slice(1),
      ],
    });
    act(() => {
      window.history.replaceState(
        {},
        "",
        "/catalog?q=noice+cancelng+hedfones&event=2c58f0a1-7d3e-4a90-8b21-6f0d5c9e4471",
      );
    });

    await waitFor(() =>
      expect(screen.getByRole("group", { name: "Lab 1 state" }).textContent).toBe(
        "source: solveddatabase: applied",
      )
    );
    expect(vi.mocked(api.labsState)).toHaveBeenCalledTimes(2);
  });

  it("holds the chips' space open before the first read lands", async () => {
    // Otherwise two chips appear beside the bag a round trip after first paint
    // and shove the header's actions sideways under the participant's cursor.
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockResolvedValue(labsFixture);
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const state = screen.getByRole("group", { name: "Lab 1 state" });
    expect(state.textContent).toBe("");
    expect(state.querySelector(".site-lab-state-pending")).toBeTruthy();

    await waitFor(() =>
      expect(state.textContent).toBe("source: brokendatabase: stale")
    );
    expect(state.querySelector(".site-lab-state-pending")).toBeNull();
  });

  it("says the lab state was not checked when the read fails", async () => {
    // A failed status call is not a verdict on the participant's repair. Showing
    // `broken` here would send someone to edit SQL that was never the problem.
    vi.mocked(api.health).mockResolvedValue(healthFixture(null));
    vi.mocked(api.labsState).mockRejectedValue(new Error("connection refused"));
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const state = await screen.findByRole("group", { name: "Lab 1 state" });
    expect(state.textContent).toBe("source: not checkeddatabase: not checked");
  });

  it("closes the storefront with official marks inside the demo contract", () => {
    render(
      <CommerceProvider>
        <Shell>
          <div>Shop content</div>
        </Shell>
      </CommerceProvider>,
    );

    const footer = screen.getByRole("contentinfo");
    const paymentList = within(footer).getByRole("list", {
      name: "Secure demo checkout payment methods",
    });
    const labels = within(paymentList)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(labels).toEqual([
      "Visa",
      "Mastercard",
      "American Express",
      "PayPal",
      "Apple Pay",
      "Google Pay",
    ]);
    expect(
      [...paymentList.querySelectorAll("img")].map((image) =>
        image.getAttribute("src"),
      ),
    ).toEqual([
      "/assets/icons/payment/visa.svg",
      "/assets/icons/payment/mastercard.svg",
      "/assets/icons/payment/amex.svg",
      "/assets/icons/payment/paypal.svg",
      "/assets/icons/payment/apple-pay.svg",
      "/assets/icons/payment/google-pay.svg",
    ]);
    expect(
      [...paymentList.querySelectorAll("img")].map((image) =>
        image.getAttribute("height"),
      ),
    ).toEqual(["20", "20", "20", "20", "20", "20"]);
    for (const image of paymentList.querySelectorAll("img")) {
      expect(image.getAttribute("alt")).toBe("");
      expect(image.getAttribute("aria-hidden")).toBe("true");
    }
    expect(paymentList.textContent).not.toMatch(/hsa|fsa|eligible/i);
    // A storefront that prints prices, stock, reviews and then payment methods has
    // to say that none of it is real. Everything else on the page is built to be
    // believed, which is exactly why this line cannot go missing.
    expect(footer.textContent).toContain("Nothing here charges a card");
    expect(footer.textContent).toContain("synthetic data");

    // No invented destinations. A shop footer is where About, Careers, Returns,
    // Accessibility and a newsletter field that posts nowhere accumulate, and a
    // footer of dead links imitates a real store worse than a short one does.
    // Every internal href has to be a path App serves.
    const served = [
      "/",
      "/catalog",
      "/labs/retrieval",
      "/mosaic-labs/hnsw",
      "/mosaic-labs/studio",
    ];
    const hrefs = within(footer)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href")!);
    const internal = hrefs.filter((href) => href.startsWith("/"));
    expect(internal.length).toBeGreaterThan(5);
    for (const href of internal) {
      expect(served).toContain(href.split("?")[0]);
    }
    // And every link that leaves does so safely, in a new tab.
    for (const link of within(footer).getAllByRole("link")) {
      if (!link.getAttribute("href")!.startsWith("http")) continue;
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noreferrer");
    }
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
