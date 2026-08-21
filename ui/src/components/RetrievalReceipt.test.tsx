// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { seedRun } from "../retrievalSeed";
import type {
  AgentCitation,
  AgentPlanStep,
  SearchResponse,
  ToolTraceStep,
} from "../types";
import {
  AgentRetrievalReceipt,
  SearchRetrievalReceipt,
} from "./RetrievalReceipt";

describe("RetrievalReceipt", () => {
  afterEach(cleanup);

  it("shows the shared six-stage vocabulary for a search response", () => {
    render(<SearchRetrievalReceipt response={seedRun} />);

    const receipt = screen.getByRole("region", {
      name: "End-to-end retrieval receipt",
    });
    expect(
      within(receipt).getByText(
        "Filters → candidates → fusion → rerank → evidence → latency",
      ),
    ).toBeTruthy();
    expect(within(receipt).getAllByRole("term")).toHaveLength(6);
    expect(within(receipt).getByText("Not requested")).toBeTruthy();
    expect(within(receipt).getByText("search receipt only")).toBeTruthy();
  });

  it("does not invent a receipt when diagnostics are unavailable", () => {
    const response: SearchResponse = { ...seedRun, diagnostics: null };
    const { container } = render(<SearchRetrievalReceipt response={response} />);

    expect(container.childElementCount).toBe(0);
  });

  it("marks a focused follow-up as inherited but requires fresh evidence", () => {
    const plan: AgentPlanStep[] = [];
    const citations: AgentCitation[] = [
      {
        number: 1,
        evidence_id: 401,
        evidence_type: "specification",
        product_id: seedRun.results[0].product_id,
        source_uri: "mosaic://product/1/specification/401",
        revision: "rev-1",
        title: "Measured specification",
        quote: "Supports the requested feature.",
      },
    ];
    const trace: ToolTraceStep[] = [
      {
        sequence: 1,
        tool: "get_product_evidence",
        detail: "Retrieved fresh evidence",
        retrieval_run_id: seedRun.search_event_id,
        result_count: 1,
        arguments: {},
        outcome: "success",
        latency_ms: 12.4,
      },
      {
        sequence: 2,
        tool: "synthesize_cited_answer",
        detail: "Authorized cited answer",
        retrieval_run_id: null,
        result_count: null,
        arguments: {},
        outcome: "success",
        latency_ms: 8.1,
      },
    ];

    render(
      <AgentRetrievalReceipt
        citations={citations}
        executionPath="focused_follow_up"
        plan={plan}
        products={seedRun.results.slice(0, 2)}
        trace={trace}
      />,
    );

    const receipt = screen.getByRole("region", {
      name: "End-to-end retrieval receipt",
    });
    expect(within(receipt).getByText("Inherited")).toBeTruthy();
    expect(within(receipt).getByText("authorized prior shortlist")).toBeTruthy();
    expect(within(receipt).getByText("replayed prior receipt")).toBeTruthy();
    expect(within(receipt).getByText("#401")).toBeTruthy();
    expect(within(receipt).getByText("2 tool receipts")).toBeTruthy();
  });
});
