import { describe, expect, it } from "vitest";
import { categoryPoolSize } from "../media";
import { editorialStories, intentionCategories } from "./DiscoverPage";
import type { Domain } from "../types";

/**
 * Discover must link to categories with a range of available photos. Stable
 * per-product choices can repeat within a page; avoiding those repeats must not
 * change a product's photo when it moves from Shop to Playground.
 *
 * Eleven is the available-photo floor: true-wireless-earbuds has eleven shots.
 * The real category without photography below remains a witness for this guard.
 */
const MIN_AVAILABLE = 11;

function tooShallow(
  entries: Array<{ label: string; category: string; domain: string }>,
) {
  return entries
    .map((entry) => ({
      label: entry.label,
      category: entry.category,
      available: categoryPoolSize(entry.category, entry.domain as Domain),
    }))
    .filter((entry) => entry.available < MIN_AVAILABLE);
}

describe("Discover entry points", () => {
  it("constrains every editorial entry to a category with enough available photos", () => {
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

  it("points every category tile at a category with enough available photos", () => {
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

  it("fails for a category that still owns no photography", () => {
    // The guard has to be able to fail, and it has to fail on something real.
    //
    // It used to demonstrate that on `acoustic-headphones` and
    // `mesh-office-chairs` -- the categories "Focus headphones" and "Quiet home
    // office" reached unconstrained. Both were repaired at source rather than
    // routed around: they joined `relatedCategories` in media.ts, so each now
    // draws on the photos from its interchangeable category.
    // Leaving them here would have left a falsifier that no longer falsifies.
    //
    // `humidifiers` replaces them, on the same terms: no plate set, no exact
    // shot, no interchangeable neighbour -- an air purifier is not a humidifier
    // -- so every row in it resolves to the one domain-neutral plate. When it
    // gets photography this test goes red, which is the signal to move the
    // falsifier to whatever is still starved rather than to delete it.
    expect(categoryPoolSize("humidifiers", "home_office")).toBe(1);
    expect(
      tooShallow([
        { label: "unconstrained", category: "humidifiers", domain: "home_office" },
      ]),
    ).toHaveLength(1);
  });

  it("records the two categories the falsifier used to name as repaired", () => {
    // Not decoration: this is what stops `relatedCategories` being quietly
    // narrowed back. Both were one photograph for twelve rows on the Lab 1
    // anchor query, which is the most-run query in the session.
    expect(categoryPoolSize("acoustic-headphones", "home_office")).toBeGreaterThanOrEqual(MIN_AVAILABLE);
    expect(categoryPoolSize("mesh-office-chairs", "home_office")).toBeGreaterThanOrEqual(MIN_AVAILABLE);
  });
});
