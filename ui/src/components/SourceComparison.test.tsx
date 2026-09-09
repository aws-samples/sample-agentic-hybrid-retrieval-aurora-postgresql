// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { AgentResponse, EvidenceRecord } from "../types";
import { showcaseCatalogPage } from "../showcase";
import { SourceComparison } from "./SourceComparison";

afterEach(cleanup);
const product = showcaseCatalogPage({}, 0, 1).products[0];
const record = (fields: Partial<EvidenceRecord>): EvidenceRecord => ({ evidence_id: 11, product_id: product.product_id, evidence_type: "product_spec", source_name: "Sample catalog", source_uri: "mosaic://evidence/11", revision: "r1", title: "Specification", text: "Has a microphone.", rating: null, is_verified: false, metadata: {}, ...fields });
const answer: AgentResponse = { agent_run_id: "run", question: "Does it fit?", answer: "A microphone is present [1].", recommendations: [product], plan: [], trace: [], citations: [{ number: 1, evidence_id: 11, product_id: product.product_id, evidence_type: "product_spec", source_uri: "mosaic://evidence/11", revision: "r1", title: "Specification", quote: "Has a microphone." }] };

it("compares the actual read records and separates a cited specification from an uncited review", () => {
  render(<SourceComparison answer={{ ...answer, retrieved_evidence: [record({}), record({ evidence_id: 12, evidence_type: "verified_review", title: "My experience", text: "Fit may vary with your setup." }), record({ evidence_id: 13, product_id: product.product_id + 1, text: "Another product's source" })] }} />);
  const specification = screen.getByRole("region", { name: `${product.title}: Specification` });
  expect(within(specification).getByText("Cited [1]")).toBeTruthy();
  const review = screen.getByRole("region", { name: `${product.title}: Review` });
  expect(within(review).getByText("Read, not cited")).toBeTruthy();
  expect(within(review).getByText("Fit may vary with your setup.")).toBeTruthy();
  expect(screen.getByText(/catalog and reviews are sample data/)).toBeTruthy();
  expect(screen.queryByText("Another product's source")).toBeNull();
});

it("reports a missing review without inventing agreement or a review record", () => {
  render(<SourceComparison answer={{ ...answer, retrieved_evidence: [record({})] }} />);
  expect(screen.getByText(/No review was retrieved/)).toBeTruthy();
  expect(screen.getAllByRole("link")).toHaveLength(1);
});

it("does not treat an older citation-only response as a complete record of retrieved evidence", () => {
  render(<SourceComparison answer={answer} />);
  expect(screen.getByText(/This saved response contains citations only/)).toBeTruthy();
  expect(screen.queryByText(/No review was retrieved/)).toBeNull();
});
