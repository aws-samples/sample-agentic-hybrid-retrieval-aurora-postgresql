import { describe, expect, it } from "vitest";
import { isPlausibleSearchEventId } from "./repairEvidence";

describe("isPlausibleSearchEventId", () => {
  it("accepts a UUID, including with surrounding whitespace", () => {
    expect(isPlausibleSearchEventId("9f92f8cc-efc2-4d81-a94a-69638d050282")).toBe(true);
    expect(isPlausibleSearchEventId("  9f92f8cc-efc2-4d81-a94a-69638d050282  ")).toBe(true);
  });

  it("rejects prose, empty input, and near-misses", () => {
    expect(isPlausibleSearchEventId("")).toBe(false);
    expect(isPlausibleSearchEventId("not-a-uuid")).toBe(false);
    expect(isPlausibleSearchEventId("9f92f8cc-efc2-4d81-a94a-69638d05028")).toBe(false);
  });
});
