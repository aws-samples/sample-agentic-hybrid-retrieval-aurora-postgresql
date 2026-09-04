// @vitest-environment jsdom

import { createElement } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { showcaseCatalogPage } from "../showcase";
import { boldRecommendationNames } from "./AskMosaic";
import { Searches } from "./agentAnswerParts";
import type { AgentPlanStep } from "../types";

afterEach(() => {
  cleanup();
});

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

describe("Searches", () => {
  /**
   * Ask Mosaic's call site passes no props, so the shared component's own
   * default must keep Shop's receipt collapsed behind a click. The Reason
   * stage opts into `open` explicitly (see ReasonStage.test.tsx); this is the
   * other half of that contrast.
   */
  it("keeps the searches receipt collapsed by default, the way Shop calls it", () => {
    const plan: AgentPlanStep[] = [
      { query: "quiet mechanical keyboard", filters: {}, purpose: "Find the quietest keyboards" },
    ];
    render(createElement(Searches, { plan }));

    const details = screen.getByText("How I searched").closest("details");
    expect(details?.hasAttribute("open")).toBe(false);
  });
});
