// @vitest-environment jsdom

import { createElement, Fragment } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { CommerceProvider } from "../../commerce";
import type { AgentCitation, ProductSummary } from "../../types";
import { AnswerSources, PickComparison } from "./AnswerComparison";

const rank = (value: number | null) => ({ rank: value, raw_score: null, rrf_contribution: null });
const monitor = (product_id: number, title: string, watts: number) => ({
  product_id,
  brand: "Dell",
  model: "UltraSharp",
  source_dataset: "reviews-2023-v2",
  listing_url: `https://example.com/${product_id}`,
  title,
  rating: 4.5,
  review_count: 12,
  specs: {
    size_in: { value: 27, source: "details.Screen Size", quote: "27 Inches" },
    usb_c_power_w: { value: watts, source: "features[1]", quote: `up to ${watts}W of power delivery` },
  },
  signals: { fts: rank(null), trigram: rank(null), semantic: rank(3), pre_rerank_rank: 4, final_rank: 1 },
}) as unknown as ProductSummary;
const picks = [
  monitor(1, "Dell UltraSharp U2720Q 27\" 4K", 90),
  monitor(2, "Dell P2721Q 27\" 4K USB-C", 65),
  monitor(3, "Dell S2722QC 27\" 4K", 65),
];
const cite = (number: number, product_id: number, evidence_type: string, quote: string) =>
  ({ number, product_id, evidence_type, evidence_id: 500 + number, source_uri: "", revision: "r1", title: "", quote }) as AgentCitation;
const citations = [
  cite(1, 1, "product_spec", "Title: Dell UltraSharp U2720Q\n27 Inches\nGet up to 90W of power delivery"),
  cite(2, 1, "customer_review", "Charges my laptop over the one cable, and the picture is sharp."),
];
const QUESTION = "A 27-inch monitor that charges my laptop, please.";

function renderAnswer(shown: ProductSummary[]) {
  return render(createElement(CommerceProvider, null, createElement(Fragment, null,
    createElement(PickComparison, {
      picks: shown, citations, questions: [QUESTION], answerId: "answer-1",
      imageByProductId: new Map(), onSelectProduct: () => {},
    }),
    createElement(AnswerSources, { picks: shown, citations, questions: [QUESTION], answerId: "answer-1" }),
  )));
}

// jsdom does not lay out, so it has no scrollIntoView.
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(cleanup);

describe("PickComparison", () => {
  it("links a cell's source number to that numbered source", () => {
    const { container } = renderAnswer(picks.slice(0, 2));
    const link = container.querySelector<HTMLAnchorElement>('.ask-compare a.ask-answer-cite[aria-label="Source 1"]')!;
    const target = document.getElementById(link.getAttribute("href")!.slice(1))!;
    expect(target.tagName).toBe("LI");
    expect(target.textContent).toContain("Record 501");
    fireEvent.click(link);
    expect(document.activeElement).toBe(target);
    expect(screen.getByText("2 sources")).toBeTruthy();
    expect(screen.getByText(/1 from a listing · 1 from a review/)).toBeTruthy();
  });

  it("gives three picks a line per label, and every value both of its headers", () => {
    const { container } = renderAnswer(picks);
    expect(container.querySelector(".ask-compare")!.getAttribute("data-layout")).toBe("stacked");
    const cells = [...container.querySelectorAll<HTMLTableCellElement>("td.ask-compare-cell")];
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      const ids = cell.headers.split(" ");
      expect(ids).toHaveLength(2);
      ids.forEach((id) => expect(document.getElementById(id)?.tagName).toBe("TH"));
    }
    expect(renderAnswer(picks.slice(0, 2)).container.querySelector(".ask-compare")!.getAttribute("data-layout")).toBe("columns");
  });
});
