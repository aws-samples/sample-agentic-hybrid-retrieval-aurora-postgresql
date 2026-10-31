// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { seedRun } from "../../retrievalSeed";
import { fixtureCatalogPage } from "../../testProducts";
import type { ProductSummary, SearchResponse } from "../../types";
import { RACE_STEPS, RankRace, advance, raceCaption, raceRows } from "./RankRace";

vi.mock("motion/react", async (original) => ({ ...await original<typeof import("motion/react")>(), useReducedMotion: () => true }));

afterEach(cleanup);

/** The run's own k, from the seeded profile rather than a second copy of the setting. */
const K = seedRun.diagnostics!.retrieval_profile.rrf_k;

type Ranks = { fts?: number; fuzzy?: number; semantic?: number; combined: number; final: number };

function ranked(base: ProductSummary, title: string, ranks: Ranks): ProductSummary {
  const arm = (rank?: number) => ({ rank: rank ?? null, raw_score: rank == null ? null : 1 / rank, rrf_contribution: rank == null ? null : 1 / (K + rank) });
  return {
    ...base,
    title,
    // A real-catalog listing, so its short name comes from its title.
    source_dataset: "reviews-2023-v2",
    signals: {
      fts: arm(ranks.fts), fuzzy: arm(ranks.fuzzy), semantic: arm(ranks.semantic),
      rrf_score: 1 / ranks.combined, pre_rerank_rank: ranks.combined, pre_rerank_score: 1 / ranks.combined,
      rerank_score: 1 / ranks.final, rerank_rank: ranks.final, final_rank: ranks.final, score_semantics: "",
    },
  } as ProductSummary;
}

const bases = fixtureCatalogPage({}, 0, 12).products;
// Ten returned products; the wanted one only semantic search found, at #10, combined #21, final #5.
const products = bases.slice(0, 10).map((base, index) => index === 9
  ? ranked(base, "ViewSonic VG2756-4K 27 Inch IPS", { semantic: 10, combined: 21, final: 5 })
  : ranked(base, `Monitor ${index + 1}`, { fts: index + 1, semantic: index + 2, combined: index + 1, final: index < 4 ? index + 1 : index + 2 }));
const viewSonic = products[9];
const response = {
  search_event_id: "race-search",
  results: products,
  diagnostics: {
    rerank_status: "applied", retrieval_profile: { rrf_k: K },
    // Fuzzy matching put one candidate on the shortlist, below the ten returned.
    candidate_counts: { fused_pool: 50, fts_in_pool: 31, fuzzy_in_pool: 1, semantic_in_pool: 30 },
  },
} as unknown as SearchResponse;
const step = (key: string) => RACE_STEPS.find((item) => item.key === key)!;

describe("raceRows", () => {
  it("orders a step's rows by that step's own rank and leaves out what it did not rank", () => {
    const rows = raceRows(products, step("fts"), null);
    expect(rows.map((row) => row.content.rank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(rows.some((row) => row.content.productId === viewSonic.product_id)).toBe(false);
  });

  it("pins a followed product that ranks below the window, at its real rank", () => {
    const rows = raceRows(products, step("combined"), viewSonic.product_id);
    expect(rows).toHaveLength(9);
    expect(rows.at(-1)?.content).toMatchObject({ productId: viewSonic.product_id, rank: 21 });
  });

  it("shows reranking's move on the final step only", () => {
    const final = raceRows(products, step("final"), viewSonic.product_id).find((row) => row.content.productId === viewSonic.product_id);
    expect(final?.content.move).toEqual({ text: "▲ 16", direction: "up" });
    expect(raceRows(products, step("combined"), null)[0].content.move).toBeNull();
  });
});

describe("raceCaption", () => {
  it("says where the followed product stands and where reranking moved it from", () => {
    expect(raceCaption(step("final"), products, response, viewSonic)).toContain("ViewSonic VG2756-4K 27 Inch IPS is #5 (was #21 combined).");
    expect(raceCaption(step("combined"), products, response, viewSonic)).toContain(`each search adds 1 / (${K} + its rank)`);
  });

  it("says when a step did not find the followed product", () => {
    expect(raceCaption(step("fts"), products, response, viewSonic)).toContain("was not found by full-text search.");
  });

  it("names a wanted product the search did not return, without guessing where it went", () => {
    const caption = raceCaption(step("final"), products, response, undefined, "ViewSonic VG2756-4K");
    expect(caption).toContain("The ViewSonic VG2756-4K is not among the 10 products this search returned.");
  });

  it("counts each search's shortlist as the chips do, and how many of those were returned", () => {
    expect(raceCaption(step("fts"), products, response, undefined)).toContain("It found 31 on the shortlist, 9 of them among the 10 shown.");
    expect(raceCaption(step("fuzzy"), products, response, undefined)).toContain("It found 1 on the shortlist, none of them among the 10 shown.");
  });
});

describe("advance", () => {
  it("settles on its target without overshooting, as a critically damped spring", () => {
    const state = { value: 0, velocity: 0, target: 100 };
    let peak = 0;
    for (let frame = 0; frame < 120 && advance(state, 1 / 60); frame += 1) peak = Math.max(peak, state.value);
    expect(state.value).toBe(100);
    expect(peak).toBeLessThanOrEqual(100);
  });
});

describe("RankRace", () => {
  it("opens on the final order under reduced motion, then follows the step a reader chooses", () => {
    const onFollow = vi.fn();
    render(<RankRace response={response} followId={viewSonic.product_id} wanted onFollow={onFollow} />);
    const steps = screen.getByRole("radiogroup", { name: "Ranking shown" });
    expect(within(steps).getByRole("radio", { name: "Reranked" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(steps).getByRole("radio", { name: "Semantic search" }));
    const list = screen.getByRole("list", { name: "Semantic search order" });
    expect(within(list).getAllByRole("button")[0].textContent).toContain("Monitor 1");
    const wanted = list.querySelector('[data-followed="wanted"]');
    expect(wanted?.textContent).toContain("#10");
    fireEvent.click(within(list).getAllByRole("button")[1]);
    expect(onFollow).toHaveBeenCalledWith(products[1].product_id);
  });

  it("leaves journey steps the race has not reached uncoloured", () => {
    render(<RankRace response={response} followId={viewSonic.product_id} wanted onFollow={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Semantic search" }));
    const nodes = [...screen.getByRole("list", { name: /at each step$/ }).querySelectorAll("li")];
    // The three searches are reached; Combined (RRF) and Reranked are ahead.
    expect(nodes.map((node) => node.hasAttribute("data-ahead"))).toEqual([false, false, false, true, true]);
  });

  it("marks searches blue, the combined order orange and the reranked order green", () => {
    render(<RankRace response={response} followId={viewSonic.product_id} wanted onFollow={() => {}} />);
    const nodes = [...screen.getByRole("list", { name: /at each step$/ }).querySelectorAll("li")];
    expect(nodes.map((node) => node.getAttribute("data-accent"))).toEqual(["retrieve", "retrieve", "retrieve", "rank", "done"]);
    expect(screen.getByRole("radio", { name: "Reranked" }).getAttribute("data-accent")).toBe("done");
  });

  it("moves between steps with the arrow keys, as a radio group does", () => {
    render(<RankRace response={response} followId={null} wanted={false} onFollow={() => {}} />);
    const final = screen.getByRole("radio", { name: "Reranked" });
    fireEvent.keyDown(final, { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "Combined (RRF)" }).getAttribute("aria-checked")).toBe("true");
  });

  it("keeps a search that returned nothing on this page, and says what it found", () => {
    render(<RankRace response={response} followId={null} wanted={false} onFollow={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Fuzzy matching" }));
    expect(screen.getByText("It found 1 on the shortlist, none of them among the 10 shown.", { selector: ".pg-race-empty" })).toBeTruthy();
  });

  it("races each step's own first products on the shortlist, faded when not returned", () => {
    const below = ranked(bases[10], "Portable Monitor 15.6", { fuzzy: 1, combined: 30, final: 31 });
    render(<RankRace response={response} pool={[below]} followId={null} wanted={false} onFollow={() => {}} />);
    expect(screen.getByText(/Each step’s first 8 on the shortlist of 50\. Faded rows are not among the 10 shown\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Fuzzy matching" }));
    const list = screen.getByRole("list", { name: "Fuzzy matching order" });
    const row = list.querySelector("[data-off-page]");
    expect(row?.textContent).toContain("#1");
    // Not followable: the Playground holds no receipt for a product it did not return.
    expect(within(list).queryAllByRole("button")).toHaveLength(0);
  });
});
