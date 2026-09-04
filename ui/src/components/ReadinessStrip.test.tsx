// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ReadinessResponse } from "../types";
import { ReadinessStrip } from "./ReadinessStrip";

const readiness: ReadinessResponse = {
  status: "ready",
  database_ready: true,
  model_space_ready: true,
  database: {
    database_name: "mosaic",
    server_version: "16.4",
    schema_ready: true,
    vector_version: "0.8.0",
    product_count: 500_000,
    embedded_product_count: 500_000,
    embedding_dimensions: 1024,
    embedding_model_ids: ["us.cohere.embed-v4:0"],
    premium_product_count: 120,
    evidence_product_count: 500_000,
    missing_retrieval_indexes: null,
    missing_retrieval_functions: null,
    exact_neighbor_ground_truth: "seeded",
    exact_neighbor_ground_truth_detail: null,
  },
  configured_models: {
    embedding: "us.cohere.embed-v4:0",
    rerank: "cohere.rerank-v3-5:0",
    agent: "us.anthropic.claude-sonnet-4-6:0",
    synthesis: "us.anthropic.claude-sonnet-4-6:0",
  },
  bedrock_credentials: { ready: true },
};

function rows() {
  return [...document.querySelectorAll(".labs-readiness-row")].map((row) => [
    row.querySelector("dt")?.textContent,
    row.querySelector("dd")?.textContent,
  ]);
}

describe("ReadinessStrip", () => {
  afterEach(cleanup);

  it("reports the nine things a lab needs before it can be believed", () => {
    render(<ReadinessStrip readiness={readiness} />);

    expect(rows()).toEqual([
      ["Aurora", "PostgreSQL 16.4"],
      ["Data", "500,000 products, 500,000 embedded"],
      ["Indexes", "all present"],
      ["Ground truth", "seeded"],
      ["Embed", "us.cohere.embed-v4:0"],
      ["Rerank", "cohere.rerank-v3-5:0"],
      ["Agent", "us.anthropic.claude-sonnet-4-6:0"],
      ["Source revision", "not checked"],
      ["Dataset manifest", "not checked"],
    ]);
  });

  it("names the missing index rather than reporting the row as present", () => {
    render(
      <ReadinessStrip
        readiness={{
          ...readiness,
          status: "blocked",
          database_ready: false,
          database: {
            ...readiness.database,
            missing_retrieval_indexes: ["product_document_trigram_gin_idx"],
          },
        }}
      />,
    );

    expect(screen.getByText("missing: product_document_trigram_gin_idx")).toBeTruthy();
    expect(screen.queryByText("all present")).toBeNull();
  });

  it("writes not checked rather than a value it does not have", () => {
    // Null covers both "the read has not landed" and "the read failed". Neither
    // is evidence about the cluster, so neither may print one.
    render(<ReadinessStrip readiness={null} />);

    expect(rows().map(([, value]) => value)).toEqual(Array(9).fill("not checked"));
    expect(screen.queryByText(/products/)).toBeNull();
  });

  it("does not report ground truth as missing when the field is absent", () => {
    // An older service does not carry `exact_neighbor_ground_truth`. Printing
    // "missing" for an absent key would send a facilitator to reseed a corpus
    // that was never reported on.
    const { exact_neighbor_ground_truth: _omitted, ...database } = readiness.database;
    render(<ReadinessStrip readiness={{ ...readiness, database }} />);

    expect(
      rows().find(([label]) => label === "Ground truth")?.[1],
    ).toBe("not checked");
  });
});
