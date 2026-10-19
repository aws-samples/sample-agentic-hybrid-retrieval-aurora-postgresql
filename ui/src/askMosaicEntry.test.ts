import { describe, expect, it } from "vitest";
import { askMosaicPromptHref } from "./askMosaicEntry";

describe("askMosaicPromptHref", () => {
  it("hands Ask Mosaic a prompt without making it a Shop search", () => {
    const href = askMosaicPromptHref("Compare listing B0 with similar monitor options.");
    const params = new URL(href, "http://shop.test").searchParams;
    expect(params.get("ask")).toBe("1");
    expect(params.get("prompt")).toBe("Compare listing B0 with similar monitor options.");
    expect(params.has("q")).toBe(false);
  });
});
