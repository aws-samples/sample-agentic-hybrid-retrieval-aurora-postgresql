// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { seedRun } from "../retrievalSeed";
import type { SearchResponse } from "../types";
import { RetrievalDiagnosticsStrip } from "./RetrievalDiagnosticsStrip";

/**
 * The strip's contract is one sentence: every figure on it is read off the
 * response the service just returned. These tests are the falsifiers for the
 * two ways it stopped being true.
 */

function withTimings(timings: Record<string, number>): SearchResponse {
  const diagnostics = seedRun.diagnostics;
  if (!diagnostics) throw new Error("the seed run must carry diagnostics");
  return { ...seedRun, diagnostics: { ...diagnostics, stage_timings_ms: timings } };
}

function breakdown(): string {
  const strip = screen.getByRole("region", {
    name: "Measured retrieval diagnostics",
  });
  const queryTime = within(strip).getByText("Query time").parentElement;
  if (!queryTime) throw new Error("the query-time tile lost its container");
  const note = queryTime.querySelector("small");
  if (!note) throw new Error("the query-time tile lost its breakdown");
  return note.textContent ?? "";
}

describe("RetrievalDiagnosticsStrip stage timings", () => {
  afterEach(cleanup);

  it("prints every stage the run reported, not a hardcoded subset", () => {
    // Measured live on 2026-09-06: the service times five stages. A three-key
    // display table dropped `coverage` and `result_persistence` -- 301 ms of a
    // 1,467 ms run -- from a strip that claims to show what the run reported.
    render(
      <RetrievalDiagnosticsStrip
        response={withTimings({
          embedding: 252.102,
          postgresql_retrieval: 680.108,
          rerank: 359.098,
          coverage: 204.417,
          result_persistence: 96.531,
        })}
      />,
    );

    expect(breakdown()).toContain(
      "Embed 252 · Postgres 680 · Rerank 359 · Coverage 204 · Persist 97",
    );
  });

  it("shows a stage the service adds later rather than silently dropping it", () => {
    // The filter, not the omission, was the defect: a stage absent from the
    // display table used to vanish with nothing to notice. An unnamed key gets a
    // readable label and sorts after the named ones.
    render(
      <RetrievalDiagnosticsStrip
        response={withTimings({ embedding: 10, guardrail_screen: 42 })}
      />,
    );

    expect(breakdown()).toContain("Embed 10 · Guardrail screen 42");
  });

  it("never reports a measured stage as zero", () => {
    // `_embed_query` keeps a 256-entry LRU, so a repeated query measures the
    // cache lookup rather than the model call: 0.006 ms, printed as `Embed 0`.
    // The Lab 1 anchor query is usually already cached from Shop, so the one
    // surface that exists to show what retrieval costs advertised the embedding
    // as free.
    render(
      <RetrievalDiagnosticsStrip
        response={withTimings({ embedding: 0.006, postgresql_retrieval: 890 })}
      />,
    );

    const text = breakdown();
    expect(text).toContain("Embed <1");
    expect(text).not.toMatch(/Embed 0\b/);
  });

  it("keeps a true zero distinguishable from an absent stage", () => {
    render(
      <RetrievalDiagnosticsStrip
        response={withTimings({ embedding: 0, rerank: 5 })}
      />,
    );

    expect(breakdown()).toContain("Embed 0 · Rerank 5");
  });

  it("says the stages do not sum to the total, and only when there are stages", () => {
    // The total is the wall clock the caller waited on; the stages are the spans
    // instrumented inside it. A participant who adds them up should learn that
    // here rather than conclude a number lied.
    render(<RetrievalDiagnosticsStrip response={withTimings({ rerank: 5 })} />);
    expect(breakdown()).toContain("do not sum to it");

    cleanup();
    render(<RetrievalDiagnosticsStrip response={withTimings({})} />);
    expect(breakdown()).toBe("No stage timings reported");
  });
});
