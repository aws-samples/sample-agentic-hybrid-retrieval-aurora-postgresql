import { describe, expect, it } from "vitest";
import { structuredAnswer } from "./SearchPage";

describe("structuredAnswer", () => {
  it("promotes the three answer-of-record labels to headings", () => {
    const answer = [
      "Summary",
      "Direct recommendation.",
      "",
      "Recommendations:",
      "- **Product** with evidence [1].",
      "",
      "Trade-offs",
      "One constraint [1].",
    ].join("\n");

    expect(structuredAnswer(answer)).toContain("## Summary");
    expect(structuredAnswer(answer)).toContain("## Recommendations");
    expect(structuredAnswer(answer)).toContain("## Trade-offs");
  });

  it("does not rewrite those words when they appear inline", () => {
    const answer = "The Summary field and Recommendations remain evidence.";
    expect(structuredAnswer(answer)).toBe(answer);
  });
});
