import { describe, expect, it } from "vitest";
import collection from "../../../data/real-shop-collection.json";
import { editorialStories } from "../shopStories";

describe("Shop landing entry points", () => {
  it("routes editorial entries and category tiles to the reviewed real-product collection", () => {
    const categoryGroups: Record<string, string> = { headphones: "headphones", chair: "chairs", monitor: "monitors" };
    const entries = editorialStories.map((story) => ({
      category: story.filters.category_key!, domain: story.filters.domain,
    }));
    expect(entries).toHaveLength(3);
    for (const entry of entries) {
      const group = collection.groups.find((item) => item.category === categoryGroups[entry.category]);
      expect(group, entry.category).toBeDefined();
      expect(new Set(group!.parent_asins).size).toBe(40);
      expect(entry.domain).toBe(entry.category === "chair" ? "home_office" : "consumer_electronics");
    }
  });
});
