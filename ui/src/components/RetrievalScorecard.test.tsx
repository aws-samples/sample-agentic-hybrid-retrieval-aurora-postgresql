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
      excluded_agent_contract_query_ids: ["G-010"],
      per_query_metrics: [],
    },
    regression_anchors: {
      passed: 4,
      total: 4,
      anchors: [
        { query_id: "G-001", product_id: 17001, type: "top_rank" },
        { query_id: "G-015", product_id: 210001, type: "top_rank" },
        { query_id: "G-015", product_id: 210002, type: "present_top_k", k: 3 },
        { query_id: "G-019", product_id: 30001, type: "top_rank" },
      ],
    },
    eligibility_contracts: {
      fixture_count: 18,
      held: true,
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
  };
}

describe("RetrievalScorecard", () => {
  afterEach(cleanup);

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
