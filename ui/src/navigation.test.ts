import { describe, expect, it } from "vitest";
import {
  RETRIEVAL_SURFACE,
  forwardedSearchFilters,
  playgroundQueryHref,
} from "./navigation";

/**
 * One request travelling through Discover, Shop and the Playground.
 *
 * The workshop's typo lesson depends on it. A shopper types `Sonorra WHC720` on
 * Discover, Shop answers it usefully, and the Playground has to report that the
 * close-spelling arm is what carried the target — for that same request. Three
 * surfaces reasoning about three different candidate pools would make the lesson
 * unprovable.
 *
 * The round trip is the contract: whatever Shop puts on the link, the Playground has
 * to rebuild into the filters it searches with. The link once forwarded gates that
 * the Playground then ignored in favour of the selected scenario's, so a forwarded
 * query was answered under the wrong eligibility and the two screens described
 * unrelated requests.
 */

const TYPO = "Sonorra WHC720";

/** The gates Shop had in force for the canonical Lab 1 request. */
const SHOP_FILTERS = {
  domain: "consumer_electronics",
  max_price_cents: 20000,
  in_stock_only: true,
};

describe("Shop to Playground hand-off", () => {
  it("carries the query verbatim, including its misspellings", () => {
    const href = playgroundQueryHref(TYPO, {});
    const params = new URLSearchParams(href.split("?")[1]);

    expect(href.startsWith(`${RETRIEVAL_SURFACE.path}?`)).toBe(true);
    expect(params.get("q")).toBe(TYPO);
  });

  it("round-trips every gate Shop applied", () => {
    const href = playgroundQueryHref(TYPO, SHOP_FILTERS);
    const rebuilt = forwardedSearchFilters(new URLSearchParams(href.split("?")[1]));

    expect(rebuilt).toEqual(SHOP_FILTERS);
  });

  it("round-trips the full gate set, so none is silently dropped", () => {
    const every = {
      domain: "home_office",
      category_key: "ergonomic-office-chairs",
      brand: "PostureWorks",
      availability: "in_stock",
      min_price_cents: 5000,
      max_price_cents: 80000,
      min_rating: 4,
      in_stock_only: true,
    };
    const href = playgroundQueryHref("chair", every);

    expect(forwardedSearchFilters(new URLSearchParams(href.split("?")[1])))
      .toEqual(every);
  });

  it("forwards no gates when Shop had none", () => {
    // An empty object, not the scenario's own filters. Inheriting those would let
    // the Playground narrow a request Shop ran across the whole catalog.
    const href = playgroundQueryHref("Focus headphones", {});

    expect(forwardedSearchFilters(new URLSearchParams(href.split("?")[1])))
      .toEqual({});
  });

  it("drops the falsy values a filter object carries for an unset gate", () => {
    // Shop's `applied_filters` reports `in_stock_only: false` and empty strings for
    // gates nobody set. Forwarding those as `in_stock_only=false` would read as a
    // gate that was considered and declined.
    const href = playgroundQueryHref("chair", {
      domain: "home_office",
      brand: "",
      availability: undefined,
      in_stock_only: false,
      min_rating: 0,
    });

    expect(forwardedSearchFilters(new URLSearchParams(href.split("?")[1])))
      .toEqual({ domain: "home_office" });
  });

  it("ignores an attribute map, which cannot survive a query string", () => {
    // `SearchFilters.attributes` is a nested object. Serialising it as
    // "[object Object]" would forward a gate the Playground could not apply, so it
    // is left out of the forwarded set entirely.
    const href = playgroundQueryHref("chair", {
      domain: "home_office",
      attributes: { headrest: true },
    });

    expect(href).not.toContain("attributes");
    expect(forwardedSearchFilters(new URLSearchParams(href.split("?")[1])))
      .toEqual({ domain: "home_office" });
  });
});
