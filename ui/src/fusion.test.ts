import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fusionLabel, isWeightedFusion } from "./fusion";

const pagesDir = fileURLToPath(new URL("./pages", import.meta.url));

describe("fusion labelling", () => {
  it("does not claim weighting for the served unweighted strategy", () => {
    expect(fusionLabel("rrf_fusion+rerank")).toBe("Reciprocal rank fusion");
    expect(isWeightedFusion("rrf_fusion+rerank")).toBe(false);
  });

  it("says weighted only when the run reports it", () => {
    expect(fusionLabel("weighted_rrf_fusion+rerank")).toBe(
      "Weighted reciprocal rank fusion",
    );
    expect(isWeightedFusion("weighted_rrf_fusion+rerank")).toBe(true);
  });

  it("renders a neutral label when no run has reported yet", () => {
    // Absent evidence must not read as a claim in either direction.
    expect(fusionLabel()).toBe("Reciprocal rank fusion");
    expect(fusionLabel(null)).toBe("Reciprocal rank fusion");
  });

  it("is case-insensitive, so a strategy rename cannot silently mislabel", () => {
    expect(isWeightedFusion("Weighted_RRF")).toBe(true);
  });

  it("no page hardcodes the weighted label", async () => {
    // The regression: a page read "Weighted RRF" while the served path was
    // unweighted. The label must come from the data, so the string may only
    // appear in this module.
    const files = (await readdir(pagesDir)).filter((name) => name.endsWith(".tsx"));
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const source = await readFile(`${pagesDir}/${name}`, "utf8");
      expect(source, `${name} hardcodes a weighted-fusion claim`).not.toMatch(
        /Weighted (RRF|reciprocal)/i,
      );
    }
  });
});
