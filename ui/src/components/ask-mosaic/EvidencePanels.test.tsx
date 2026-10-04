// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ProductSummary } from "../../types";
import { FINAL_LABEL, FUSED_LABEL } from "../../retrievalLanguage";
import { Ranking } from "./EvidencePanels";

afterEach(() => {
  cleanup();
});

const arm = (rank: number | null) => ({ rank, raw_score: null, rrf_contribution: null });

function leader(overrides: Record<string, unknown>): ProductSummary {
  return {
    product_id: 1,
    model: "UltraSharp",
    signals: {
      fts: arm(null),
      trigram: arm(null),
      semantic: arm(2),
      pre_rerank_rank: 4,
      final_rank: 1,
      rerank_score: null,
      ...overrides,
    },
  } as unknown as ProductSummary;
}

describe("Ranking", () => {
  it("prints each position with its number", () => {
    const { container } = render(<Ranking candidates={[leader({})]} />);
    expect(container.textContent).toContain("#4");
    expect(container.textContent).toContain("#1");
  });

  it.each([null, undefined])("prints a dash, never #%s, for a missing position", (missing) => {
    const { container } = render(
      <Ranking candidates={[leader({ pre_rerank_rank: missing, final_rank: missing })]} />,
    );
    const positions = [...container.querySelectorAll("div")]
      .filter((row) => row.querySelector("dt"))
      .map((row) => [row.querySelector("dt")!.textContent, row.querySelector("dd")!.textContent]);
    const byLabel = new Map(positions);
    expect(byLabel.get(FUSED_LABEL)).toBe("-");
    expect(byLabel.get(FINAL_LABEL)).toBe("-");
  });
});
