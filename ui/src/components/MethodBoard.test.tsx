// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { seedRun } from "../retrievalSeed";
import type { ProductSummary, SearchResponse } from "../types";
import { MethodBoard } from "./MethodBoard";

afterEach(cleanup);

const none = { rank: null, raw_score: null, rrf_contribution: null };

function row(id: number, title: string, ranks: {
  fts?: number | null; trigram?: number | null; semantic?: number | null; combined: number; final: number;
}): ProductSummary {
  const base = structuredClone(seedRun.results[0]);
  const arm = (rank: number | null | undefined) => (rank == null ? none : { rank, raw_score: 1, rrf_contribution: 0.01 });
  return {
    ...base,
    product_id: id,
    title,
    signals: {
      ...base.signals!,
      fts: arm(ranks.fts),
      trigram: arm(ranks.trigram),
      semantic: arm(ranks.semantic),
      pre_rerank_rank: ranks.combined,
      final_rank: ranks.final,
    },
  };
}

function run(results: ProductSummary[], rerank: "applied" | "disabled" = "applied"): SearchResponse {
  return { ...seedRun, results, diagnostics: { ...seedRun.diagnostics!, rerank_status: rerank } };
}

function column(name: string) {
  return screen.getByRole("heading", { name }).closest("article") as HTMLElement;
}

const images = new Map<number, string>();
const products = [
  row(1, "Alpha monitor", { fts: 3, semantic: 2, combined: 1, final: 2 }),
  row(2, "Wanted monitor", { semantic: 10, combined: 21, final: 5 }),
  row(3, "Gamma monitor", { fts: 1, trigram: 4, semantic: 7, combined: 2, final: 1 }),
];

describe("MethodBoard", () => {
  it("lists the five columns in order with the real rank from each signal", () => {
    render(<MethodBoard response={run(products)} images={images} />);
    expect(screen.getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual([
      "Full-text search", "Fuzzy matching", "Semantic search", "Combined in Aurora", "Reranked",
    ]);
    const semantic = within(column("Semantic search"));
    const ranks = semantic.getAllByRole("listitem").map((item) => item.querySelector(".method-rank")!.textContent);
    expect(ranks).toEqual(["2", "7", "10"]);
    expect(within(column("Reranked")).getByText("from combined #21")).toBeTruthy();
  });

  it("limits a column to five rows and says so when it has none", () => {
    const many = Array.from({ length: 8 }, (_, index) =>
      row(100 + index, `P${index}`, { fts: index + 1, combined: index + 1, final: index + 1 }));
    render(<MethodBoard response={run(many)} images={images} />);
    expect(within(column("Full-text search")).getAllByRole("listitem")).toHaveLength(5);
    expect(within(column("Fuzzy matching")).getByText(/^None of the \d+ shown$/)).toBeTruthy();
  });

  it("badges the wanted product by tier and rings its row", () => {
    render(<MethodBoard response={run(products)} wantedId={2} targetRank={5} images={images} />);
    expect(within(column("Reranked")).getByText("Wanted #5").getAttribute("data-tier")).toBe("target");
    expect(within(column("Combined in Aurora")).getByText("Wanted #21").getAttribute("data-tier")).toBe("lower");
    expect(within(column("Full-text search")).getByText("Wanted product: not found here").getAttribute("data-tier")).toBe("unranked");
    const ringed = column("Semantic search").querySelector("[data-target]");
    expect(ringed?.textContent).toContain("Wanted monitor");
  });

  it("names the wanted product when the search did not return it", () => {
    render(<MethodBoard response={run(products)} wantedId={999} wantedName="ViewSonic VG2756-4K" images={images} />);
    expect(screen.getByText(/The ViewSonic VG2756-4K is not among the \d+ shown\./)).toBeTruthy();
    expect(document.querySelector(".method-badge")).toBeNull();
  });

  it("says Not reranked when the request was not reranked", () => {
    render(<MethodBoard response={run(products, "disabled")} images={images} />);
    expect(screen.getByRole("heading", { name: "Not reranked" })).toBeTruthy();
    expect(screen.queryByText("from combined #21")).toBeNull();
  });

  it("selects a product from its row", () => {
    const onSelect = vi.fn();
    render(<MethodBoard response={run(products)} images={images} onSelect={onSelect} />);
    fireEvent.click(within(column("Full-text search")).getByRole("button", { name: /Gamma monitor, Full-text search rank 1/ }));
    expect(onSelect).toHaveBeenCalledWith(3);
  });

  it("loads thumbnails lazily at their drawn size", () => {
    render(<MethodBoard response={run(products)} images={images} />);
    const image = document.querySelector(".method-row img")!;
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(image.getAttribute("width")).toBe("36");
  });

  it("shows each row's movement against the stage before it", () => {
    render(<MethodBoard response={run(products)} images={images} />);
    const move = (name: string, title: string) =>
      within(column(name)).getByText(title).closest("li")!.querySelector(".rank-move")!;
    // Wanted monitor: best search 10, combined 21, final 5.
    expect(move("Reranked", "Wanted monitor").getAttribute("data-move")).toBe("up");
    expect(move("Reranked", "Wanted monitor").textContent).toContain("16");
    expect(move("Combined in Aurora", "Wanted monitor").getAttribute("data-move")).toBe("down");
    expect(move("Combined in Aurora", "Wanted monitor").textContent).toContain("11");
    // Gamma: best search 1, combined 2, final 1.
    expect(move("Combined in Aurora", "Gamma monitor").getAttribute("data-move")).toBe("down");
    expect(move("Reranked", "Gamma monitor").getAttribute("data-move")).toBe("up");
    expect(within(column("Reranked")).getByText(/from combined #21/)).toBeTruthy();
  });

  it("calls a row new when the earlier stage never ranked it, and unchanged when it did not move", () => {
    const unranked = row(7, "No search found me", { combined: 4, final: 4 });
    render(<MethodBoard response={run([unranked])} images={images} />);
    expect(within(column("Combined in Aurora")).getByText("new").getAttribute("data-move")).toBe("new");
    expect(column("Reranked").querySelector(".rank-move")?.getAttribute("data-move")).toBe("same");
  });

  it("follows the final number one across every column, and lets the wanted product win", () => {
    const { rerender } = render(<MethodBoard response={run(products)} images={images} />);
    const topRows = () => [...document.querySelectorAll("[data-top]")].map((item) => item.textContent);
    expect(topRows().length).toBe(5);
    expect(topRows().every((text) => text!.includes("Gamma monitor"))).toBe(true);
    rerender(<MethodBoard response={run(products)} wantedId={3} images={images} />);
    expect(document.querySelectorAll("[data-top]")).toHaveLength(0);
    expect(document.querySelectorAll("[data-target]")).toHaveLength(5);
  });
});
