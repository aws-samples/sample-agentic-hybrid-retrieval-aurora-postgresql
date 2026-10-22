// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { seedRun } from "../retrievalSeed";
import type { SearchResponse } from "../types";
import { PipelineStrip } from "./PipelineStrip";

afterEach(cleanup);

function chips() {
  const strip = screen.getByRole("region", { name: "How this search ran" });
  return [...strip.querySelectorAll("li.pipeline-chip")] as HTMLElement[];
}

describe("PipelineStrip", () => {
  it("reads every count and timing from the response", () => {
    render(<PipelineStrip response={seedRun} />);
    const counts = seedRun.diagnostics!.candidate_counts;
    const text = chips().map((chip) => chip.textContent);
    expect(text).toEqual([
      `Full-text search${counts.fts_in_pool}`,
      `Fuzzy matching${counts.trigram_in_pool}`,
      `Semantic search${counts.semantic_in_pool}`,
      `Combined (RRF) · shortlist${counts.fused_pool}`,
      `Reranked · Cohere Rerank${counts.fused_pool}`,
      `${seedRun.results.length} shown`,
    ]);
    const [, , , combined, reranked] = chips();
    expect(combined.title).toContain("Search in Aurora 847 ms");
    expect(reranked.title).toBe("Rerank 929 ms");
    // No explanatory paragraph: the chips and the link are all the strip says.
    expect(screen.getByRole("region", { name: "How this search ran" }).querySelector("p")).toBeNull();
  });

  it("links to this exact saved search in the Playground", () => {
    render(<PipelineStrip response={seedRun} />);
    const link = screen.getByRole("link", { name: /Watch the ranking change in the Playground/ });
    expect(new URL(link.getAttribute("href")!, "http://x").searchParams.get("event"))
      .toBe(seedRun.search_event_id);
  });

  it("marks a search with nothing in the pool as hollow, and a fault only when told", () => {
    const empty: SearchResponse = {
      ...seedRun,
      diagnostics: {
        ...seedRun.diagnostics!,
        candidate_counts: { ...seedRun.diagnostics!.candidate_counts, trigram_in_pool: 0 },
      },
    };
    const { rerender } = render(<PipelineStrip response={empty} />);
    expect(within(chips()[1]).getByText("0")).toBeTruthy();
    expect(chips()[1].dataset.dot).toBe("none");
    rerender(<PipelineStrip response={empty} faultArm="trigram" />);
    expect(chips()[1].dataset.dot).toBe("fault");
    expect(chips()[0].dataset.dot).not.toBe("fault");
  });

  it("says so when the request was not reranked, without inventing a timing", () => {
    const plain: SearchResponse = {
      ...seedRun,
      diagnostics: { ...seedRun.diagnostics!, rerank_status: "disabled", stage_timings_ms: {} },
    };
    render(<PipelineStrip response={plain} />);
    expect(chips().map((chip) => chip.textContent)).toContain("Not reranked");
    expect(chips().every((chip) => !/\d+ ms/.test(chip.title))).toBe(true);
  });
});
