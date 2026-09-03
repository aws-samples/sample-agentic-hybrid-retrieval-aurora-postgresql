// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { QueryCoverage } from "../types";

import { CoverageNotice } from "./CoverageNotice";

const unanchored: QueryCoverage = {
  confidence: "unanchored",
  unmatched_terms: ["A2342"],
  terms: [],
  note: "Nothing in the catalog matches the term 'A2342'.",
};

afterEach(cleanup);

/** Visible text of the notice, whitespace-normalized. */
const text = () =>
  (screen.getByTestId("coverage-notice").textContent ?? "")
    .replace(/\s+/g, " ")
    .trim();

describe("CoverageNotice", () => {
  it("names the term the catalog does not carry", () => {
    render(<CoverageNotice coverage={unanchored} />);

    expect(text()).toContain("Nothing in the catalog matches A2342.");
    expect(text()).toContain("The results below answer the rest of the request.");
  });

  it("joins several unmatched terms readably", () => {
    render(
      <CoverageNotice
        coverage={{ ...unanchored, unmatched_terms: ["A2342", "DK-9981X"] }}
      />,
    );

    expect(text()).toContain("Nothing in the catalog matches A2342 or DK-9981X.");
  });

  it("stays silent on a grounded request", () => {
    render(
      <CoverageNotice
        coverage={{
          confidence: "grounded",
          unmatched_terms: [],
          terms: [],
          note: "",
        }}
      />,
    );

    expect(screen.queryByTestId("coverage-notice")).toBeNull();
  });

  it("stays silent when coverage could not be computed", () => {
    // The database has no vocabulary or no function. Rendering a caveat from
    // that would assert something the run never established.
    render(
      <CoverageNotice
        coverage={{
          confidence: "unavailable",
          unmatched_terms: [],
          terms: [],
          note: "Corpus vocabulary is empty.",
        }}
      />,
    );

    expect(screen.queryByTestId("coverage-notice")).toBeNull();
  });

  it("stays silent when the response carries no coverage at all", () => {
    const { rerender } = render(<CoverageNotice coverage={null} />);
    expect(screen.queryByTestId("coverage-notice")).toBeNull();

    rerender(<CoverageNotice coverage={undefined} />);
    expect(screen.queryByTestId("coverage-notice")).toBeNull();
  });

  it("stays silent if unanchored arrives with no terms to name", () => {
    // Defensive: a notice that cannot say which word failed tells a shopper
    // nothing actionable, so it is worse than no notice.
    render(<CoverageNotice coverage={{ ...unanchored, unmatched_terms: [] }} />);

    expect(screen.queryByTestId("coverage-notice")).toBeNull();
  });
});
