// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { seedRun } from "../../retrievalSeed";
import { fixtureCatalogPage } from "../../testProducts";
import type { ProductSummary, SearchResponse } from "../../types";
import { FusionTable } from "./FusionTable";

afterEach(cleanup);

/** The run's own k, from the seeded profile rather than a second copy of the setting. */
const K = seedRun.diagnostics!.retrieval_profile.rrf_k;

function ranked(base: ProductSummary, title: string, combined: number, ranks: { fts?: number; semantic?: number }, reported?: number): ProductSummary {
  const arm = (rank?: number) => ({ rank: rank ?? null, raw_score: null, rrf_contribution: rank == null ? null : 1 / (K + rank) });
  const signals = { fts: arm(ranks.fts), fuzzy: arm(), semantic: arm(ranks.semantic) };
  const sum = (signals.fts.rrf_contribution ?? 0) + (signals.semantic.rrf_contribution ?? 0);
  return {
    ...base,
    title,
    source_dataset: "reviews-2023-v2",
    signals: {
      ...signals,
      rrf_score: reported ?? sum, pre_rerank_rank: combined, pre_rerank_score: sum,
      rerank_score: null, rerank_rank: null, final_rank: combined, score_semantics: "",
    },
  } as ProductSummary;
}

const bases = fixtureCatalogPage({}, 0, 8).products;
const products = bases.slice(0, 7).map((base, index) => ranked(base, `Monitor ${index + 1}`, index + 1, { fts: index + 1, semantic: index + 3 }));
const response = (results: ProductSummary[]) => ({
  search_event_id: "fusion", results, diagnostics: { retrieval_profile: { rrf_k: K } },
}) as unknown as SearchResponse;

function rows() {
  return within(screen.getByRole("region", { name: "How each product reached its combined position" })).getAllByRole("row").slice(1);
}

it("prints each search's 1 / (k + rank), the sum and the reported score", () => {
  render(<FusionTable response={response(products)} followId={null} images={new Map()} />);
  expect(screen.getByText(/with/).textContent).toContain(`k = ${K}`);
  const first = rows()[0];
  expect(first.textContent).toContain("Monitor 1");
  expect(first.textContent).toContain(`1 / (${K} + 1)`);
  expect(first.textContent).toContain((1 / (K + 1)).toFixed(4));
  expect(first.textContent).toContain("not found");
  const reported = first.querySelector(".pg-fusion-reported")!;
  expect(reported.hasAttribute("data-agrees")).toBe(true);
  expect(reported.textContent).toBe((1 / (K + 1) + 1 / (K + 3)).toFixed(4));
});

it("flags a reported score that does not equal the sum of its shares", () => {
  const broken = [ranked(bases[0], "Monitor 1", 1, { fts: 1, semantic: 3 }, 0.05), ...products.slice(1)];
  render(<FusionTable response={response(broken)} followId={null} images={new Map()} />);
  expect(rows()[0].textContent).toContain("does not match the sum");
});

it("shows the first five and the followed product, then every product on request", () => {
  render(<FusionTable response={response(products)} followId={products[6].product_id} images={new Map()} />);
  expect(rows()).toHaveLength(6);
  expect(rows()[5].textContent).toContain("Monitor 7");
  expect(rows()[5].hasAttribute("data-followed")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Show all 7" }));
  expect(rows()).toHaveLength(7);
  expect(screen.getByRole("button", { name: "Show the first 5" })).toBeTruthy();
});

it("states nothing when the run reported no k", () => {
  const { container } = render(<FusionTable response={{ ...response(products), diagnostics: {} } as SearchResponse} followId={null} images={new Map()} />);
  expect(container.textContent).toBe("");
});
