import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { seedProvenance, seedRun } from "./retrievalSeed";
import type { ResultSignals } from "./types";

/**
 * The committed seed run has to be a measurement, not a drawing.
 *
 * The surface it feeds used to print "This replay explains the retrieval flow, not
 * a measured run" over hand-written rank arrays. Replacing that with a committed
 * file only helps if the file cannot drift back into fiction, so these checks
 * re-derive the fusion arithmetic that `mosaic_search.search_hybrid_rrf` performs.
 * A response somebody assembled to make a point will not satisfy them, and the
 * last test in this file proves that by breaking one.
 */

const repo = fileURLToPath(new URL("../..", import.meta.url));

function contributionsAgree(signals: ResultSignals, rrfK: number): true | string {
  let total = 0;
  for (const arm of ["fts", "trigram", "semantic"] as const) {
    const { rank, rrf_contribution: contribution } = signals[arm];
    if (rank === null) {
      if (contribution !== null) {
        return `${arm} has no rank but reports contribution ${contribution}`;
      }
      continue;
    }
    if (contribution === null) return `${arm} has rank ${rank} but no contribution`;
    const expected = 1 / (rrfK + rank);
    if (Math.abs(contribution - expected) > 1e-9) {
      return `${arm} rank ${rank} should contribute ${expected}, reports ${contribution}`;
    }
    total += contribution;
  }
  if (Math.abs(signals.rrf_score - total) > 1e-9) {
    return `rrf_score ${signals.rrf_score} does not equal the contribution sum ${total}`;
  }
  return true;
}

describe("committed retrieval seed run", () => {
  it("names the producer that wrote it, and that producer exists", () => {
    expect(seedProvenance.producer).toBe("scripts/capture_retrieval_seed.py");
    expect(existsSync(repo + seedProvenance.producer)).toBe(true);
    expect(seedProvenance.captured_at).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(seedProvenance.search_event_id).toBe(seedRun.search_event_id);
  });

  it("carries the diagnostics the matrix reads its column measures from", () => {
    expect(seedRun.diagnostics).not.toBeNull();
    const profile = seedRun.diagnostics!.retrieval_profile;
    expect(profile.rrf_k).toBeGreaterThan(0);
    expect(profile.fused_limit).toBeGreaterThanOrEqual(seedRun.results.length);
    expect(seedRun.results.length).toBeGreaterThan(1);
  });

  it("reproduces the fusion arithmetic Aurora performed for every row", () => {
    const rrfK = seedRun.diagnostics!.retrieval_profile.rrf_k;
    for (const product of seedRun.results) {
      expect(product.signals, `product ${product.product_id} has no signals`).toBeTruthy();
      expect(
        contributionsAgree(product.signals!, rrfK),
        `product ${product.product_id}`,
      ).toBe(true);
    }
  });

  it("ranks the rows densely, so before and after are comparable", () => {
    const finals = seedRun.results.map((product) => product.signals!.final_rank).sort(
      (left, right) => left - right,
    );
    expect(finals).toEqual(finals.map((_, index) => index + 1));

    const fused = new Set(seedRun.results.map((product) => product.signals!.pre_rerank_rank));
    expect(fused.size).toBe(seedRun.results.length);
  });

  it("exercises more than one retrieval arm, or it teaches nothing", () => {
    const armsUsed = (["fts", "trigram", "semantic"] as const).filter((arm) =>
      seedRun.results.some((product) => product.signals![arm].rank !== null),
    );
    expect(armsUsed.length).toBeGreaterThanOrEqual(2);
  });

  it("rejects a response whose contributions were written to fit a claim", () => {
    // The permanent falsifier. Every check above passes on the committed file, so
    // without this one there is no evidence they would fail on anything.
    const rrfK = seedRun.diagnostics!.retrieval_profile.rrf_k;
    const honest = seedRun.results[0].signals!;
    expect(contributionsAgree(honest, rrfK)).toBe(true);

    const invented: ResultSignals = {
      ...honest,
      semantic: { rank: 1, raw_score: 0.99, rrf_contribution: 0.5 },
      rrf_score: 0.9,
    };
    expect(contributionsAgree(invented, rrfK)).not.toBe(true);

    const phantom: ResultSignals = {
      ...honest,
      semantic: { rank: null, raw_score: null, rrf_contribution: 0.01 },
    };
    expect(contributionsAgree(phantom, rrfK)).not.toBe(true);
  });
});
