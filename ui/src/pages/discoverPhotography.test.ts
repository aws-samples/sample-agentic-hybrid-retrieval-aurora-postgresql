import { describe, expect, it } from "vitest";
import { productImageMap } from "../media";
import { editorialStories, intentionCategories } from "./DiscoverPage";
import type { Domain, ProductSummary } from "../types";

/**
 * Every Discover entry point has to land somewhere with enough photography to fill
 * a page of results.
 *
 * The regression this exists to stop: an entry point shipped unconstrained, so
 * "Focus headphones" retrieved twelve products from `acoustic-headphones` — a
 * subcategory with no commissioned photography — and Shop drew the same
 * domain-neutral plate twelve times. "Quiet home office" did the same through
 * `mesh-office-chairs`.
 *
 * The hero chips are no longer covered here. They are the three labs' own
 * queries now, gated by each lab's own filters, and a lab's gates are fixed by
 * `data/evals/mosaic_labs_missions.json` rather than chosen for photography. A
 * category-depth rule over them would be a rule this file cannot enforce: the
 * only remedy would be to change a lab's request.
 *
 * A live query is the only way to know which subcategory a phrase actually
 * retrieves, and these tests have no database. What they hold is the half that is
 * checkable offline and that was the real defect: the constraint exists, and the
 * category it names can illustrate a full page. A chip pointed at a category with
 * one plate cannot show twelve products whatever the retrieval does.
 *
 * The assertion runs the real resolver over a synthetic page rather than checking a
 * pool size, because the number that matters is how many distinct photographs a
 * shopper ends up looking at. `productImageMap` places product-bound shots first and
 * then spreads the surplus, so a pool one short of a page yields one duplicate pair
 * and nothing worse.
 */

/** `pageSize` in CatalogPage. */
const PAGE_SIZE = 12;

/**
 * One duplicate pair is the floor, and it is a measured one: `true-wireless-earbuds`
 * owns eleven photographs, which is the deepest pool the audio category behind
 * "Travel-ready audio" has. Anything below this is a page that reads as repetition —
 * a pool of six draws every photograph twice, and a pool of one draws the same
 * picture twelve times, which is the defect that shipped.
 */
const MIN_DISTINCT = PAGE_SIZE - 1;

/**
 * A page of rows in one category with no photography of their own.
 *
 * Ids are spaced the way catalog ids are, because `spread` mixes the id to pick a
 * starting point in the pool and consecutive ids would understate the spread.
 */
function pageOf(categoryKey: string, domain: Domain): ProductSummary[] {
  return Array.from({ length: PAGE_SIZE }, (_, index) => ({
    product_id: 400_000 + index * 37,
    sku: `PROBE-${index}`,
    title: "Probe product",
    short_description: "",
    domain,
    category_key: categoryKey,
    category_path: categoryKey,
    brand: "Probe",
    model: `P-${index}`,
    price_cents: 10_000,
    list_price_cents: 10_000,
    currency: "USD",
    rating: 4,
    review_count: 1,
    availability: "in_stock" as const,
    inventory_count: 1,
    attributes: {},
    tags: [],
    catalog_asset_key: null,
    canonical_group_id: null,
    media_tier: null,
    is_flagship: false,
    is_retrieval_anchor: false,
    image_url: null,
    image_source: null,
    signals: null,
    sources: [],
  }));
}

function distinctPhotographs(categoryKey: string, domain: string): number {
  const assigned = productImageMap(pageOf(categoryKey, domain as Domain));
  return new Set(assigned.values()).size;
}

function tooShallow(
  entries: Array<{ label: string; category: string; domain: string }>,
) {
  return entries
    .map((entry) => ({
      label: entry.label,
      category: entry.category,
      distinct: distinctPhotographs(entry.category, entry.domain),
    }))
    .filter((entry) => entry.distinct < MIN_DISTINCT);
}

describe("Discover entry points", () => {
  it("constrains every editorial entry to a category that can fill a page", () => {
    expect(
      tooShallow(
        editorialStories.map((story) => ({
          label: story.title,
          category: story.filters.category_key ?? "",
          domain: story.filters.domain ?? "",
        })),
      ),
    ).toEqual([]);
  });

  it("points every category tile at a category that can fill a page", () => {
    expect(
      tooShallow(
        intentionCategories.map((category) => ({
          label: category.label,
          category: category.categoryKey,
          domain: category.domain,
        })),
      ),
    ).toEqual([]);
  });

  it("fails for the plateless categories the unconstrained chips reached", () => {
    // The guard has to be able to fail. These are the real categories "Focus
    // headphones" and "Quiet home office" retrieved with no constraint: neither owns
    // a photograph, so both collapse to the one domain-neutral plate for the domain.
    expect(distinctPhotographs("acoustic-headphones", "home_office")).toBe(1);
    expect(distinctPhotographs("mesh-office-chairs", "home_office")).toBe(1);
    expect(
      tooShallow([
        { label: "unconstrained", category: "acoustic-headphones", domain: "home_office" },
      ]),
    ).toHaveLength(1);
  });
});
