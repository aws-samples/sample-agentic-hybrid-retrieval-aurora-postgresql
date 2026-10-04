// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { fixtureCatalogPage } from "../../testProducts";
import type { AgentResponse, RetrievalRunResponse, ToolTraceStep } from "../../types";
import { BuilderView } from "./BuilderView";
import { CommerceProvider } from "../../commerce";
import { TopPick } from "./Picks";
import { SourceList } from "./SourceList";
import type { RunData } from "./findings";
import { pickFacts, pickRequirements } from "./pickFacts";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const [chair, monitor] = fixtureCatalogPage({}, 0, 2).products;
const RECORDED_K = 61;
const RUN_ID = "cc3a32d8-1111-4222-8333-444444444444";

const search: ToolTraceStep = {
  sequence: 1,
  tool: "search_products",
  detail: "Retrieved a bounded set.",
  retrieval_run_id: RUN_ID,
  result_count: 2,
  arguments: { query: "Steelcase Gesture chair", category_key: "chair" },
  outcome: "success",
  origin: "model",
  latency_ms: 4080,
};

const response = {
  agent_run_id: "fc97f09b-0000-4000-8000-000000000000",
  session_id: null,
  question: "q",
  answer: "a",
  plan: [],
  recommendations: [chair],
  citations: [],
  trace: [search],
  outcome: "grounded",
  memory: {},
} as unknown as AgentResponse;

const run: RunData = { path: "full_retrieval", plan: [], trace: [search], citations: [] };

const candidate = (productId: number, finalRank: number) => ({
  product_id: productId,
  result_rank: finalRank,
  fts_rank: finalRank === 1 ? 1 : null,
  trigram_rank: null,
  semantic_rank: finalRank,
  fused_rank: finalRank + 1,
  rerank_rank: null,
  scores: { rerank: 0.9 - finalRank / 10 },
  provenance: { channels: { fts: { rrf_contribution: 0.016 }, vector: { rrf_contribution: 0.015 } } },
  eligible: true,
});

const receipt = {
  run: {
    search_event_id: RUN_ID,
    retrieval_profile: { rrf_k: RECORDED_K },
    rerank_model_id: "rerank-model",
    candidate_counts: { fused_pool: 50, fts_in_pool: 1, trigram_in_pool: 36, semantic_in_pool: 38 },
    total_latency_ms: 3540,
  },
  candidates: [candidate(chair.product_id, 1), candidate(monitor.product_id, 2)],
} as unknown as RetrievalRunResponse;

describe("BuilderView ranks", () => {
  beforeEach(() => {
    vi.spyOn(api, "product").mockResolvedValue({ ...monitor } as never);
  });

  it("reads each search's saved receipt by its run id and prints its recorded ranks", async () => {
    const read = vi.spyOn(api, "retrievalEvent").mockResolvedValue(receipt);
    render(<BuilderView response={response} run={run} durationMs={43_500} />);

    expect(read).toHaveBeenCalledWith(RUN_ID);
    const ranked = await screen.findByRole("region", { name: "How it ranked" });
    await waitFor(() => expect(within(ranked).getByText(/Search cc3a32d8/)).toBeTruthy());
    expect(within(ranked).getByRole("button", { name: "Chair", pressed: true })).toBeTruthy();
    expect(ranked.textContent).toContain(`RRF, k = ${RECORDED_K} · rerank rerank-model`);
    const rows = within(ranked).getAllByRole("row");
    // Header plus the two receipt rows, the recommended product named from the response.
    expect(rows).toHaveLength(3);
    expect(rows[1].textContent).toContain(`${chair.brand} ${chair.model}`.trim());
    expect(rows[1].textContent).toContain("0.800");
    // The split bar lives under the name, so there is no column of its own to scroll to.
    const headers = within(ranked).getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toEqual(["Final", "Product", "Exact", "Spell", "Mean", "Comb.", "Rerank"]);
    expect(rows[1].querySelector(".ask-rank-name .ask-rrf-bar")).not.toBeNull();
  });

  it("says so, and shows the recommended products' own ranks, when the receipt cannot be read", async () => {
    vi.spyOn(api, "retrievalEvent").mockRejectedValue(new Error("gone"));
    render(<BuilderView response={response} run={run} />);

    expect(
      await screen.findByText(/Ranks for the recommended products\. The saved search could not be read\./),
    ).toBeTruthy();
  });

  it("lists the run's facts and what the response does not record", async () => {
    vi.spyOn(api, "retrievalEvent").mockResolvedValue(receipt);
    render(<BuilderView response={response} run={run} durationMs={43_500} />);

    const builder = screen.getByRole("region", { name: "Builder view" });
    expect(within(builder).getByText("run fc97f09b")).toBeTruthy();
    expect(within(builder).getByText("43.5 s")).toBeTruthy();
    expect(within(builder).getByText("memory off")).toBeTruthy();
    fireEvent.click(within(builder).getByRole("button", { name: "Chair" }));
    expect(within(builder).getByText("tokens")).toBeTruthy();
  });
});

const ANSWER = "The Logitech lists active noise cancellation [1]. A reviewer reports crystal-clear audio with no complaints from callers [2].";

describe("pickFacts lines", () => {
  const cite = (number: number, type: string, quote: string) => ({
    number, evidence_id: number, evidence_type: type, product_id: chair.product_id,
    source_uri: "u", revision: "r", title: "t", quote,
  });
  const listing = cite(1, "product_spec",
    "Title: Logitech Zone 900 Headset\n\nCategories: Electronics > Headphones\n\nDescription:\nTake control of your acoustic experience at home. Active noise cancellation blocks out the noise around you.");
  const review = cite(2, "customer_review",
    "This is my second purchase of the headset.my original was purchased in 2020. The audio is crystal clear and no one ever complains about my audio.<br /><br />Well worth every penny.");

  it("uses whole lines that support the claim, never boilerplate or fragments", () => {
    const facts = pickFacts(chair, [listing, review], ANSWER);
    expect(facts).toEqual([
      { text: "Active noise cancellation blocks out the noise around you.", number: 1 },
      { text: "“The audio is crystal clear and no one ever complains about my audio.”", number: 2 },
    ]);
    expect(facts.map((fact) => fact.text).join(" ")).not.toMatch(/Title:|Categories:|<br|…/);
  });

  it("renders the citation pill inside the last word's nowrap span, so it cannot wrap alone", () => {
    const answer = ANSWER;
    render(
      <CommerceProvider>
        <TopPick
          product={chair} index={0} rows={[]} citations={[listing, review]} answer={answer}
          answerId="a" builder={false} highlighted={false} onHighlight={() => {}} onSelectProduct={() => {}}
        />
      </CommerceProvider>,
    );
    const pill = screen.getByRole("link", { name: "Source 1" });
    const glued = pill.closest(".ask-nowrap")!;
    expect(glued.textContent).toBe("you.1");
    expect(glued.closest("p")?.textContent).toContain("Active noise cancellation blocks out the noise around you.");
  });
});

describe("source list lines", () => {
  it("shows the cited line from a listing and from a review", () => {
    const cite = (number: number, type: string, quote: string) => ({
      number, evidence_id: number, evidence_type: type, product_id: chair.product_id,
      source_uri: "u", revision: "r", title: "t", quote,
    });
    render(<SourceList
      answer={ANSWER} answerId="a" builder={false} products={[chair]}
      citations={[
        cite(1, "product_spec", "Title: X\n\nCategories: A > B\n\nDescription:\nActive noise cancellation blocks out the noise around you."),
        cite(2, "customer_review", "Meh start of review. The audio is crystal clear and no one ever complains.<br />Fine."),
      ]}
    />);
    const list = screen.getByRole("region", { name: "Sources" });
    expect(within(list).getByText("“Active noise cancellation blocks out the noise around you.”")).toBeTruthy();
    expect(within(list).getByText("“The audio is crystal clear and no one ever complains.”")).toBeTruthy();
    expect(list.textContent).not.toMatch(/Title:|Categories:|<br/);
  });
});

describe("pickFacts", () => {
  const citation = (number: number, type: string, quote: string) => ({
    number,
    evidence_id: number,
    evidence_type: type,
    product_id: chair.product_id,
    source_uri: "u",
    revision: "r",
    title: "t",
    quote,
  });

  it("quotes one listing record and one review, each with its citation number", () => {
    const facts = pickFacts(chair, [
      citation(5, "product_spec", "fully adjustable arms, adjustable lumbar"),
      citation(6, "customer_review", "I instantly felt relief the first day of use."),
    ]);
    expect(facts).toEqual([
      { text: "fully adjustable arms, adjustable lumbar", number: 5 },
      { text: "“I instantly felt relief the first day of use.”", number: 6 },
    ]);
  });

  it("passes over a listing's title record, which only repeats the name", () => {
    const facts = pickFacts(chair, [
      citation(1, "product_spec", "Title: Steelcase Gesture Office Chair, Licorice"),
      citation(2, "customer_review", "Finally pain free!"),
    ]);
    expect(facts.map((fact) => fact.number)).toEqual([2]);
    expect(facts[0].text).toBe("“Finally pain free!”");
  });

  it("never attributes another product's record to the pick", () => {
    const other = { ...citation(1, "product_spec", "x"), product_id: -1 };
    expect(pickFacts({ ...chair, specs: undefined }, [other])).toEqual([]);
  });

  it("reads requirement verdicts from the comparison rows", () => {
    expect(
      pickRequirements(
        [{ key: "usb_c_power_w", label: "100W charging", changed: true, requested: true, cells: [
          { text: "90 W", source: "listing", citations: [3], status: "not_met" },
        ] }],
        0,
      ),
    ).toEqual([{ label: "100W charging", status: "not_met", value: "90 W", citations: [3] }]);
  });
});
