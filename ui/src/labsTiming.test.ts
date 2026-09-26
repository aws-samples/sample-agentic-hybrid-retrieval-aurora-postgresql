import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcDir = fileURLToPath(new URL(".", import.meta.url));

/**
 * Every `.ts`/`.tsx` source file under `ui/src`, skipping tests.
 *
 * A test file is allowed to hardcode a duration to describe a fixture (see
 * this file's own `it.each` below, or a mocked API response), so it is
 * excluded from the set this gate scans.
 */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" ? [] : sourceFiles(full);
    }
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    return [full];
  });
}

/**
 * A digit immediately next to "minute(s)" or "min", the shape a hand-typed
 * session timing takes ("10-minute", "40 min", "20minutes").
 *
 * `duration_minutes`, `total_minutes` and similar field names are not
 * matched: no digit sits next to "min" in an identifier, only a word
 * boundary. Reading `mission.duration_minutes` and printing the number it
 * holds is the required path; assigning a second number of its own next to
 * the word "minutes" is the second copy this test exists to catch.
 */
const TIMING_LITERAL = /\b\d{1,3}[\s-]?min(ute)?s?\b/i;

describe("workshop timings stay sourced from the mission contract", () => {
  it("never hardcodes a minute count in UI source", () => {
    const offenders = sourceFiles(srcDir)
      .map((file) => ({ file, match: TIMING_LITERAL.exec(readFileSync(file, "utf8"))?.[0] }))
      .filter((entry): entry is { file: string; match: string } => Boolean(entry.match));

    expect(offenders).toEqual([]);
  });

  it("is provably able to fail: the falsifier this gate declares", () => {
    // Rule 2 (house standards): an assertion without a demonstrated falsifier
    // is decoration. `40-minute` is exactly the literal AGENTS.md forbids
    // ("a numeric literal assigned to a limit- or weight-shaped name") for a
    // timing rather than a retrieval limit.
    expect(TIMING_LITERAL.test("Protect the 40-minute hands-on budget.")).toBe(true);
    expect(TIMING_LITERAL.test("mission.duration_minutes")).toBe(false);
    expect(TIMING_LITERAL.test(`${10} minutes`)).toBe(true);
  });
});
