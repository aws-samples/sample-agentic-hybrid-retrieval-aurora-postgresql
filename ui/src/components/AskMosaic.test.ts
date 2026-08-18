import { describe, expect, it } from "vitest";
import { showcaseCatalogPage } from "../showcase";
import { boldRecommendationNames } from "./AskMosaic";

const [first, second] = showcaseCatalogPage({}, 0, 2).products;

describe("boldRecommendationNames", () => {
  it("bolds grounded product titles and brand-model references", () => {
    const answer = [
      `${first.title} is the best fit [1].`,
      `${second.brand} ${second.model} is another strong option [2].`,
    ].join("\n\n");

    expect(boldRecommendationNames(answer, [first, second])).toBe(
      [
        `**${first.title}** is the best fit [1].`,
        `**${second.brand} ${second.model}** is another strong option [2].`,
      ].join("\n\n"),
    );
  });

  it("does not double-wrap emphasis already authored by synthesis", () => {
    const answer = `**${first.title}** is the best fit [1].`;

    expect(boldRecommendationNames(answer, [first])).toBe(answer);
  });

  it("leaves product-like prose alone when it is not in the shortlist", () => {
    const answer = "A different product would be cheaper.";

    expect(boldRecommendationNames(answer, [first])).toBe(answer);
  });
});
