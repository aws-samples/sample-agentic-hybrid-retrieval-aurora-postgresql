// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { seedRun } from "../retrievalSeed";
import type { ProductSummary, ResultSignals } from "../types";
import { ProductReceiptBody } from "./ProductReceipt";

const found = (rank: number, contribution: number) => ({
  rank,
  raw_score: 0.5,
  rrf_contribution: contribution,
});
const missed = { rank: null, raw_score: null, rrf_contribution: null };

function product(signals: ResultSignals | null, specs: ProductSummary["specs"] = {}) {
  return { ...seedRun.results[0], signals, specs } as ProductSummary;
}

const signals: ResultSignals = {
  fts: found(3, 0.0159),
  trigram: missed,
  semantic: found(1, 0.0164),
  rrf_score: 0.0323,
  pre_rerank_rank: 2,
  pre_rerank_score: 0.0323,
  rerank_score: 0.912,
  final_rank: 1,
  score_semantics: "rrf",
};

describe("ProductReceiptBody", () => {
  afterEach(cleanup);

  it("itemizes every method, then the totals", () => {
    const { container } = render(
      <ProductReceiptBody product={product(signals)} diagnostics={seedRun.diagnostics} />,
    );

    const lines = [...container.querySelectorAll("ol > li")].map((line) => line.textContent);
    expect(lines).toEqual([
      "Exact terms#30.0159position 3 · 1 ÷ (60 + 3)",
      "Close spellingno matchno match for this request",
      "Meaning match#10.0164position 1 · 1 ÷ (60 + 1)",
      "Before reranking#20.0323position 2 of the 50 sent to reranking",
      "Reranked0.912Cohere Rerank relevance score",
      "Final position#1",
    ]);
  });

  it("states a method that missed without inventing a position for it", () => {
    render(<ProductReceiptBody product={product(signals)} diagnostics={seedRun.diagnostics} />);

    const missed = screen.getByText("Close spelling").closest("li")!;
    expect(missed.className).toContain("missed");
    expect(within(missed).queryByText(/#/)).toBeNull();
    expect(within(missed).getByText("no match for this request")).toBeTruthy();
  });

  it("omits the reranker line when the search recorded no rerank score", () => {
    const { container } = render(
      <ProductReceiptBody
        product={product({ ...signals, rerank_score: null })}
        diagnostics={seedRun.diagnostics}
      />,
    );

    expect(container.textContent).not.toContain("Reranked");
    expect(container.textContent).toContain("Final position#1");
  });

  it("omits the arithmetic and the reranking-pool position when the response carries no diagnostics", () => {
    const { container } = render(<ProductReceiptBody product={product(signals)} diagnostics={null} />);

    // The rank and its fusion contribution still print from the signals alone.
    expect(container.textContent).toContain("Exact terms#30.0159");
    expect(container.textContent).toContain("Before reranking#20.0323");
    // Nothing here names a k or a pool size Mosaic did not receive.
    expect(container.textContent).not.toContain("÷");
    expect(container.textContent).not.toContain("sent to reranking");
    expect(container.querySelector(".receipt-pool-bar")).toBeNull();
    // A method that missed needs no diagnostics to say so.
    expect(container.textContent).toContain("no match for this request");
  });

  it("falls back to a generic relevance-score label when the rerank model id is not Cohere's", () => {
    const { container } = render(
      <ProductReceiptBody
        product={product(signals)}
        diagnostics={{ ...seedRun.diagnostics!, rerank_model_id: null }}
      />,
    );

    expect(container.textContent).toContain("Reranked0.912relevance score");
    expect(container.textContent).not.toContain("Cohere Rerank relevance score");
  });

  it("draws the reranking-pool position as a share of the recorded pool size", () => {
    const { container } = render(
      <ProductReceiptBody product={product(signals)} diagnostics={seedRun.diagnostics} />,
    );

    // pre_rerank_rank 2 of a fused_pool of 50: 4% from the left edge.
    const dot = container.querySelector<HTMLElement>(".receipt-pool-bar i")!;
    expect(dot.style.left).toBe("4%");
  });

  it("quotes the listing verbatim beside each stated fact", () => {
    render(
      <ProductReceiptBody
        product={product(signals, {
          size_in: { value: 27, source: "title", quote: "27-inch UHD monitor" },
        })}
      />,
    );

    const states = screen.getByRole("region", { name: "What the listing states" });
    expect(within(states).getByText("27-inch UHD monitor")).toBeTruthy();
  });

  it("leaves out the listing section when the listing states nothing typed", () => {
    render(<ProductReceiptBody product={product(signals)} />);

    expect(screen.queryByRole("region", { name: "What the listing states" })).toBeNull();
  });

  it("renders nothing for a product without recorded signals", () => {
    const { container } = render(<ProductReceiptBody product={product(null)} />);

    expect(container.innerHTML).toBe("");
  });
});
