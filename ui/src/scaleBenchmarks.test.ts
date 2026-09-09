import { describe, expect, it } from "vitest";
import { comparableScanModes, scanModes } from "./scaleBenchmarks";
import type { HnswFilterLevel, HnswFilterMode } from "./types";

const row = (mode: HnswFilterMode["iterative_scan"], effort: number, memory: number) => ({
  iterative_scan: mode, ef_search: effort, scan_mem_multiplier: memory,
  scan_mem_mb: memory * 4, rows_returned: 5, recall_at_k: 0.5, server_ms: 2,
}) as HnswFilterMode;
const level = (modes: HnswFilterMode[]) => ({ modes }) as HnswFilterLevel;

describe("comparableScanModes", () => {
  it("compares ordering with the same effort and memory, regardless of record order", () => {
    const matched = scanModes.map((mode) => row(mode, 80, 1));
    const all = [...scanModes.map((mode) => row(mode, 40, 2)), ...matched,
      row("off", 40, 1), row("strict_order", 40, 1)].reverse();
    expect(comparableScanModes(level(all))).toEqual(matched);
  });

  it("withholds an incomplete comparison instead of mixing settings", () => {
    expect(comparableScanModes(level([
      row("off", 40, 1), row("strict_order", 80, 1), row("relaxed_order", 40, 2),
    ]))).toEqual([]);
    expect(comparableScanModes()).toEqual([]);
  });
});
