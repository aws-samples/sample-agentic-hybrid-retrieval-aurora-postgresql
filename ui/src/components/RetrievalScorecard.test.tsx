// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { RetrievalScorecardResponse } from "../types";
import { RetrievalScorecard, SCORECARD_PENDING_HEADLINE } from "./RetrievalScorecard";

/**
 * Ruling R3's gate, restated as a component test: with the artifact's
 * measured revision not equal to the revision currently running (or
 * measured from a dirty tree), section A must not render
 * `Recall@10 0.8246`-style numbers as current system quality. Every test
 * below that asserts absence is paired with a positive assertion, per house
 * standards rule 7's witness requirement -- an empty component would also
 * pass an absence-only check.
 */

vi.mock("../api", () => ({
  api: { scorecard: vi.fn() },
}));

const DISTINCTIVE_RECALL = "0.7654";
const DISTINCTIVE_MRR = "0.6543";
const DISTINCTIVE_NDCG = "0.5432";

const ABLATION_PENDING_NOTE = `${SCORECARD_PENDING_HEADLINE}: ablation fixture note.`;

function stageAblationFixture(
  overrides: Partial<RetrievalScorecardResponse["stage_ablation"]> = {},
): RetrievalScorecardResponse["stage_ablation"] {
  return {
    attributed: true,
    attribution_note: "Measured at the revision currently running: abcabcabcabc.",
    measured_at: "2026-08-27T00:00:00Z",
    spread_note:
      "20 queries and 74 judgments cannot separate small differences between arms.",
    scored_query_count: 2,
    arms: [
      {
        key: "semantic_only",
        label: "Semantic only",
        description: "Dense cosine ranking alone, no fusion, no rerank.",
        recall_at_10: 0.5,
        mrr: 0.55,
        ndcg_at_10: 0.4111,
        ndcg_at_10_min: 0.0,
        ndcg_at_10_max: 1.0,
        ndcg_at_10_stdev: 0.42,
        ndcg_at_10_query_wins: 1,
      },
      {
        key: "rrf_fused_no_rerank",
        label: "RRF fused, reranking off",
        description: "The served fusion function with reranking disabled.",
        recall_at_10: 0.9111,
        mrr: 0.8222,
        ndcg_at_10: 0.7333,
        ndcg_at_10_min: 0.1,
        ndcg_at_10_max: 1.0,
        ndcg_at_10_stdev: 0.24,
        ndcg_at_10_query_wins: 1,
      },
      {
        key: "rrf_fused_reranked",
        label: "RRF fused + managed reranking (served path)",
        description: "The production path, recomputed from the served results CSV.",
        recall_at_10: 0.9333,
        mrr: 0.9444,
        ndcg_at_10: 0.8555,
        ndcg_at_10_min: 0.3,
        ndcg_at_10_max: 1.0,
        ndcg_at_10_stdev: 0.21,
        ndcg_at_10_query_wins: 2,
      },
    ],
    candidate_recall_ceiling: {
      pool_recall_ceiling: 0.95,
      judged_relevant_never_fetched: 1,
      description: "The ceiling reranking could ever reach.",
    },
    per_query: [
      {
        query_id: "G-Q1",
        query_text: "first ablation query",
        ndcg_at_10: {
          semantic_only: 0.0,
          rrf_fused_no_rerank: 0.6308,
          rrf_fused_reranked: 1.0,
        },
        pool_recall: 1.0,
        relevant_count: 1,
        found_in_pool: 1,
        missed_product_ids: [],
      },
      {
        query_id: "G-Q2",
        query_text: "second ablation query",
        ndcg_at_10: {
          semantic_only: 1.0,
          rrf_fused_no_rerank: 1.0,
          rrf_fused_reranked: 1.0,
        },
        pool_recall: 1.0,
        relevant_count: 1,
        found_in_pool: 1,
        missed_product_ids: [],
      },
    ],
    ...overrides,
  };
}

function scorecardFixture(
  overrides: Partial<RetrievalScorecardResponse["provenance"]> = {},
): RetrievalScorecardResponse {
  return {
    provenance: {
      measured_at: "2026-08-23T21:53:32.664198Z",
      query_set: "data/evals/canonical_queries.jsonl",
      query_set_sha256: "a".repeat(64),
      scored_query_set_sha256: "b".repeat(64),
      ranked_result_sha256: "c".repeat(64),
      dataset_manifest_sha256: "d".repeat(64),
      models: { embedding: "us.cohere.embed-v4:0", rerank: "cohere.rerank-v3-5:0" },
      aurora_configuration: { engine: "aurora-postgresql" },
      hnsw_settings: {},
      retrieval_profile: {},
      database_instance_id: "test-instance",
      strategy: "rrf_fusion+rerank+exact_sku_preservation",
      source_revision: "0".repeat(40),
      source_worktree_dirty: false,
      current_source_revision: "1".repeat(40),
      current_source_worktree_dirty: false,
      attributed: false,
      attribution_note: `${SCORECARD_PENDING_HEADLINE}: fixture note.`,
      ...overrides,
    },
    retrieval_quality: {
      sample_size: 19,
      canonical_query_count: 20,
      sample_description: "A curated teaching and evaluation set, fixture edition.",
      recall_at_10: Number(DISTINCTIVE_RECALL),
      mrr: Number(DISTINCTIVE_MRR),
      ndcg_at_10: Number(DISTINCTIVE_NDCG),
      metric_explanations: {
        "recall@10": "Share of graded-relevant products retrieved in the top 10.",
        mrr: "How early the first relevant result appears.",
        "ndcg@10": "How well the top 10 are ordered once relevance differs.",
      },
      excluded_agent_contract_query_ids: ["G-021"],
      per_query_metrics: [],
    },
    regression_anchors: {
      passed: 4,
      total: 4,
      // Mirrors the service: sections B and C follow provenance rather than
      // asserting success from an artifact that may no longer describe the
      // running revision. A fixture that pinned these to `true` regardless
      // would hide exactly the defect the stale-rendering test below covers.
      verified_for_running_revision: overrides.attributed ?? true,
      anchors: [
        { query_id: "G-001", product_id: 17001, type: "top_rank" },
        { query_id: "G-014", product_id: 210001, type: "top_rank" },
        { query_id: "G-014", product_id: 210002, type: "present_top_k", k: 3 },
        { query_id: "G-018", product_id: 30001, type: "top_rank" },
      ],
    },
    eligibility_contracts: {
      fixture_count: 18,
      held: (overrides.attributed ?? true) ? true : null,
      description: "Hard-negative eligibility fixtures, fixture edition.",
      fixture_query_ids: ["G-001", "G-002"],
    },
    agent_contracts: {
      guarantees: [
        {
          key: "retrieval_scope",
          label: "Retrieval scope",
          description: "The agent may act only on what its own retrieval returned.",
          assertion_names: ["retrieval_tool_called", "expected_products_considered"],
          falsifiers: ["falsifier one", "falsifier two"],
          fixture_count: null,
        },
        {
          key: "compare_boundary",
          label: "Compare boundary",
          description: "A comparison cannot widen past the recommendation shortlist.",
          assertion_names: ["comparison_tool_called"],
          falsifiers: ["falsifier three"],
          fixture_count: null,
        },
        {
          key: "evidence_authorization",
          label: "Evidence authorization",
          description: "Evidence visible to the model is not automatically usable.",
          assertion_names: ["evidence_tool_called"],
          falsifiers: ["falsifier four"],
          fixture_count: null,
        },
        {
          key: "citation_resolution",
          label: "Citation resolution",
          description: "Every citation must resolve to a real evidence record.",
          assertion_names: ["citation_ids_resolve"],
          falsifiers: ["falsifier five"],
          fixture_count: null,
        },
        {
          key: "tool_contract",
          label: "Tool contract",
          description: "Every tool call is checked against a registered contract.",
          assertion_names: ["structured_constraints_extracted"],
          falsifiers: ["falsifier six"],
          fixture_count: 5,
        },
      ],
    },
    stage_ablation: stageAblationFixture(),
  };
}

describe("RetrievalScorecard", () => {
  afterEach(cleanup);

  it("stops sections B and C claiming verification when unattributed", async () => {
    // Section A already withholds. B and C used to render a complete N/N and
    // "Fixtures held" from the same stale artifact, which reads as success the
    // measurement cannot support. The counts stay -- they are real -- but the
    // labels and copy must stop asserting present-tense verification.
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({ attributed: false }),
    );
    render(<RetrievalScorecard />);

    expect(await screen.findByText("Fixtures (unverified)")).toBeTruthy();
    expect(screen.queryByText("Fixtures held")).toBeNull();
    expect(
      screen.getByText(/Verified at the revision that was measured/i),
    ).toBeTruthy();
    // The real counts survive: withholding data would be its own dishonesty.
    expect(screen.getByText("4 / 4")).toBeTruthy();
    expect(screen.getByText("18")).toBeTruthy();
  });

  it("labels sections B and C as held once the measurement is attributed", async () => {
    // Independence from the test above: the same two assertions must invert on
    // an attributed payload, so neither is simply always true.
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture({ attributed: true }));
    render(<RetrievalScorecard />);

    expect(await screen.findByText("Fixtures held")).toBeTruthy();
    expect(screen.queryByText("Fixtures (unverified)")).toBeNull();
    expect(screen.queryByText(/Verified at the revision that was measured/i)).toBeNull();
  });

  it("withholds the metric values when the measured revision does not match", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({ attributed: false }),
    );
    render(<RetrievalScorecard />);

    // The exact, owner-specified headline -- not a paraphrase.
    expect(await screen.findByText(SCORECARD_PENDING_HEADLINE)).toBeTruthy();

    // Negative half: none of the three numeric values reach the DOM anywhere.
    expect(screen.queryByText(DISTINCTIVE_RECALL)).toBeNull();
    expect(screen.queryByText(DISTINCTIVE_MRR)).toBeNull();
    expect(screen.queryByText(DISTINCTIVE_NDCG)).toBeNull();

    // Positive pairing (rule 7): the component is not simply empty. It still
    // explains what each metric means and still renders the other sections.
    expect(
      screen.getByText("Share of graded-relevant products retrieved in the top 10."),
    ).toBeTruthy();
    expect(screen.getByText(/PASS \/ total/i)).toBeTruthy();
    expect(screen.getByText("B. Golden regression anchors")).toBeTruthy();
    expect(screen.getByText("C. Eligibility and filter contracts")).toBeTruthy();
    expect(screen.getByText("D. Agent and evidence contracts")).toBeTruthy();
  });

  it("shows the real metric values once the measured revision matches and is clean", async () => {
    const same = "2".repeat(40);
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({
        attributed: true,
        source_revision: same,
        source_worktree_dirty: false,
        current_source_revision: same,
        attribution_note: `Measured at the revision currently running: ${same.slice(0, 12)}.`,
      }),
    );
    render(<RetrievalScorecard />);

    // Positive half: the three real numbers actually render.
    expect(await screen.findByText(DISTINCTIVE_RECALL)).toBeTruthy();
    expect(screen.getByText(DISTINCTIVE_MRR)).toBeTruthy();
    expect(screen.getByText(DISTINCTIVE_NDCG)).toBeTruthy();

    // Negative pairing: the pending headline is absent once metrics are shown.
    expect(screen.queryByText(SCORECARD_PENDING_HEADLINE)).toBeNull();
  });

  it("hides the metrics when the matching revision was measured from a dirty tree", async () => {
    const same = "3".repeat(40);
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({
        attributed: false,
        source_revision: same,
        source_worktree_dirty: true,
        current_source_revision: same,
        attribution_note: `${SCORECARD_PENDING_HEADLINE}: measured from an unclean worktree.`,
      }),
    );
    render(<RetrievalScorecard />);

    expect(await screen.findByText(SCORECARD_PENDING_HEADLINE)).toBeTruthy();
    expect(screen.queryByText(DISTINCTIVE_RECALL)).toBeNull();
  });

  it("never mixes the golden-anchor PASS count into the IR metrics", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture({ attributed: true }));
    render(<RetrievalScorecard />);
    await screen.findByText(DISTINCTIVE_RECALL);

    // The anchor figure's own value is the PASS/total pair, never a metric.
    const anchorFigure = screen.getByText("4 / 4").closest(".labs-figure");
    expect(anchorFigure).toBeTruthy();
    for (const value of [DISTINCTIVE_RECALL, DISTINCTIVE_MRR, DISTINCTIVE_NDCG]) {
      expect(within(anchorFigure as HTMLElement).queryByText(value)).toBeNull();
    }

    // And the reverse: the anchor count never leaks into section A's own figures.
    const qualitySection = screen
      .getByText("A. Retrieval quality")
      .closest("section") as HTMLElement;
    expect(within(qualitySection).queryByText("4 / 4")).toBeNull();
  });

  // --- Per-query and golden-anchor labels: legible identifiers, per rule 7 --
  //
  // The committed artifact predates `query_text`/`concept_label` on both
  // `per_query_metrics` and `deterministic_release_checks`, so today's real
  // payload has neither. These two pairs of tests are the ones the task
  // calls out as mattering most: the absent-labels path must never surface
  // `undefined`/`null`/an empty element, and the present-labels path must put
  // the query text ahead of the de-emphasised `G-0NN` id, not merely render
  // both strings somewhere on the page.

  it("renders the bare query_id for each per-query row when the artifact carries no labels", async () => {
    const rows = [
      { query_id: "G-001", "recall@10": 1, reciprocal_rank: 1, "ndcg@10": 1 },
      { query_id: "G-002", "recall@10": 0.5, reciprocal_rank: 0.5, "ndcg@10": 0.6 },
    ];
    const base = scorecardFixture({ attributed: false });
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      retrieval_quality: { ...base.retrieval_quality, per_query_metrics: rows },
    });
    render(<RetrievalScorecard />);

    const disclosure = (
      await screen.findByText("View per-query results")
    ).closest("details") as HTMLElement;

    // Witness, independent of the render: exactly the two rows the fixture
    // supplied, not a count re-derived from the same `.map` that renders them.
    expect(within(disclosure).getAllByRole("listitem")).toHaveLength(2);
    expect(within(disclosure).getByText("G-001")).toBeTruthy();
    expect(within(disclosure).getByText("G-002")).toBeTruthy();

    // Negative half: no stand-in text for the missing label anywhere in it.
    expect(disclosure.textContent).not.toMatch(/undefined|null/i);
  });

  it("shows a per-query row's text before its de-emphasised query_id once labels are present", async () => {
    const rows = [
      {
        query_id: "G-002",
        query_text: "Sonora WH-C720",
        concept_label: "Exact model alias",
        "recall@10": 1,
        reciprocal_rank: 1,
        "ndcg@10": 1,
      },
    ];
    const base = scorecardFixture({ attributed: true });
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      retrieval_quality: { ...base.retrieval_quality, per_query_metrics: rows },
    });
    render(<RetrievalScorecard />);

    const disclosure = (
      await screen.findByText("View per-query results")
    ).closest("details") as HTMLElement;
    const textNode = within(disclosure).getByText("Sonora WH-C720");
    const idNode = within(disclosure).getByText("G-002");

    // Assert the relationship -- text precedes id in document order -- not
    // merely that both strings exist somewhere in the disclosure.
    expect(
      textNode.compareDocumentPosition(idNode) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(idNode.tagName).toBe("CODE");
    expect(within(disclosure).getByText("Exact model alias")).toBeTruthy();
  });

  it("renders the bare query_id for a golden anchor when the artifact carries no anchor labels", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture({ attributed: true }));
    render(<RetrievalScorecard />);

    const disclosure = (await screen.findByText("View anchors")).closest(
      "details",
    ) as HTMLElement;

    expect(within(disclosure).getByText("G-001")).toBeTruthy();
    expect(disclosure.textContent).not.toMatch(/undefined|null/i);
  });

  it("shows a golden anchor's query text before its de-emphasised query_id once labels are present", async () => {
    const base = scorecardFixture({ attributed: true });
    const labeledAnchor = {
      query_id: "G-001",
      product_id: 17001,
      type: "top_rank" as const,
      query_text: "Sonora WH-C720 headphones",
      concept_label: "Exact identity",
    };
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      regression_anchors: { ...base.regression_anchors, anchors: [labeledAnchor] },
    });
    render(<RetrievalScorecard />);

    const disclosure = (await screen.findByText("View anchors")).closest(
      "details",
    ) as HTMLElement;
    const textNode = within(disclosure).getByText("Sonora WH-C720 headphones");
    const idNode = within(disclosure).getByText("G-001");

    expect(
      textNode.compareDocumentPosition(idNode) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(idNode.tagName).toBe("CODE");
    expect(within(disclosure).getByText("Exact identity")).toBeTruthy();
  });

  it("explains in participant language why one of twenty canonical queries is not scored", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture({ attributed: true }));
    render(<RetrievalScorecard />);

    await screen.findByText(DISTINCTIVE_RECALL);

    expect(
      screen.getByText(
        /19 of the 20 canonical queries are scored for search relevance below/i,
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/multi-step agent tool orchestration/i),
    ).toBeTruthy();
  });

  it("labels section C as not a relevance judgment, with the harness's own fixture count", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture());
    render(<RetrievalScorecard />);

    await screen.findByText(SCORECARD_PENDING_HEADLINE);

    expect(screen.getByText("18")).toBeTruthy();
    expect(
      screen.getByText(/not a relevance judgment: no Recall, MRR, or nDCG/i),
    ).toBeTruthy();
  });

  it("backs every agent/evidence guarantee with a real assertion name and falsifier", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture());
    render(<RetrievalScorecard />);

    await screen.findByText("D. Agent and evidence contracts");

    for (const label of [
      "Retrieval scope",
      "Compare boundary",
      "Evidence authorization",
      "Citation resolution",
      "Tool contract",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }

    const disclosure = screen.getByText("View assertion falsifiers").closest("details");
    expect(disclosure).toBeTruthy();
    expect(within(disclosure as HTMLElement).getByText("falsifier one")).toBeTruthy();
    expect(
      within(disclosure as HTMLElement).getByText("structured_constraints_extracted"),
    ).toBeTruthy();
  });

  it("shows an error rather than a blank stage when the artifact route fails", async () => {
    vi.mocked(api.scorecard).mockRejectedValue(new Error("scorecard unavailable"));
    render(<RetrievalScorecard />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("scorecard unavailable");
  });
});

// --- Section E: stage ablation, gated independently from section A --------

describe("RetrievalScorecard stage ablation", () => {
  afterEach(cleanup);

  it("renders every arm's recall, MRR, and nDCG with its own per-query spread", async () => {
    const base = scorecardFixture({ attributed: true });
    vi.mocked(api.scorecard).mockResolvedValue(base);
    render(<RetrievalScorecard />);

    await screen.findByText("E. Stage ablation");

    expect(screen.getByText("Semantic only")).toBeTruthy();
    expect(screen.getByText("RRF fused, reranking off")).toBeTruthy();
    expect(
      screen.getByText("RRF fused + managed reranking (served path)"),
    ).toBeTruthy();
    expect(
      screen.getByText(/Recall@10 0\.9111 · MRR 0\.8222 · nDCG@10 0\.7333/),
    ).toBeTruthy();
    expect(screen.getByText(/stdev 0\.2400/)).toBeTruthy();
    expect(screen.getByText(/Wins on nDCG@10: 2 of 2 queries/)).toBeTruthy();
  });

  it("shows the candidate-recall ceiling as its own figure, not folded into an arm", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({ attributed: true }),
    );
    render(<RetrievalScorecard />);

    await screen.findByText("E. Stage ablation");

    expect(screen.getByText("0.9500")).toBeTruthy();
    const ceilingFigure = screen.getByText("0.9500").closest(".labs-figure");
    expect(ceilingFigure).toBeTruthy();
    expect(within(ceilingFigure as HTMLElement).getByText("Pool recall ceiling")).toBeTruthy();
    // The count of judged-relevant products the pool never fetched is a
    // sibling figure, never merged into the ceiling's own value.
    expect(screen.getByText("Judged-relevant never fetched").closest(".labs-figure"))
      .not.toBe(ceilingFigure);
  });

  it("withholds the ablation when its own artifact is not attributed, independently of section A", async () => {
    const base = scorecardFixture({ attributed: true });
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      stage_ablation: stageAblationFixture({
        attributed: false,
        attribution_note: ABLATION_PENDING_NOTE,
      }),
    });
    render(<RetrievalScorecard />);

    // Section A's own numbers still render: the two gates are independent.
    expect(await screen.findByText(DISTINCTIVE_RECALL)).toBeTruthy();

    // Exactly one pending headline on the page -- section A is attributed,
    // only section E's is not.
    expect(screen.getAllByText(SCORECARD_PENDING_HEADLINE)).toHaveLength(1);
    expect(screen.queryByText("Semantic only")).toBeNull();
    expect(screen.queryByText("0.9500")).toBeNull();
    expect(screen.getByTestId("stage-ablation-pending")).toBeTruthy();
  });

  it("shows the ablation while section A's own metrics are pending, independently", async () => {
    const base = scorecardFixture({ attributed: false });
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      stage_ablation: stageAblationFixture({ attributed: true }),
    });
    render(<RetrievalScorecard />);

    await screen.findByText(SCORECARD_PENDING_HEADLINE);

    expect(screen.getByText("Semantic only")).toBeTruthy();
    expect(screen.getByText("0.9500")).toBeTruthy();
    expect(screen.queryByTestId("stage-ablation-pending")).toBeNull();
  });

  it("renders the per-query nDCG@10 breakdown for every arm, keyed by query", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(
      scorecardFixture({ attributed: true }),
    );
    render(<RetrievalScorecard />);

    const disclosure = (
      await screen.findByText("View per-query nDCG@10 by arm")
    ).closest("details") as HTMLElement;

    expect(within(disclosure).getAllByRole("listitem")).toHaveLength(2);
    const rows = within(disclosure).getAllByRole("listitem");
    const g1Row = rows.find((row) => row.textContent?.includes("first ablation query"));
    expect(g1Row).toBeTruthy();
    expect(within(g1Row as HTMLElement).getByText("G-Q1")).toBeTruthy();
    // G-Q1: semantic missed it (0.0000) while the served path found it at
    // rank 1 (1.0000) -- both values must be legible in the same row.
    expect(within(g1Row as HTMLElement).getByText(/Semantic only 0\.0000/)).toBeTruthy();
    expect(
      (g1Row as HTMLElement).textContent,
    ).toContain("RRF fused + managed reranking (served path) 1.0000");
  });

  it("always exposes its measurement provenance, including when withheld", async () => {
    const base = scorecardFixture({ attributed: true });
    vi.mocked(api.scorecard).mockResolvedValue({
      ...base,
      stage_ablation: stageAblationFixture({
        attributed: false,
        attribution_note: ABLATION_PENDING_NOTE,
      }),
    });
    render(<RetrievalScorecard />);

    const disclosure = (
      await screen.findByText("View stage-ablation provenance")
    ).closest("details") as HTMLElement;
    expect(within(disclosure).getByText(ABLATION_PENDING_NOTE)).toBeTruthy();
  });

  it("carries the owner-specified honesty note about sample size and spread", async () => {
    vi.mocked(api.scorecard).mockResolvedValue(scorecardFixture());
    render(<RetrievalScorecard />);

    await screen.findByText("E. Stage ablation");

    expect(
      screen.getByText(/cannot separate small differences between arms/i),
    ).toBeTruthy();
  });
});
