import { describe, expect, it } from "vitest";
import {
  coreMosaicLabs,
  retrievalExampleHref,
  supportingMosaicChecks,
} from "./labMissions";

describe("participant query contract", () => {
  it("keeps three participant requests and five controls inside three labs", () => {
    const proofAnchors = [
      ...coreMosaicLabs,
      ...supportingMosaicChecks.filter((check) => check.core),
    ];

    expect(coreMosaicLabs).toHaveLength(3);
    expect(proofAnchors).toHaveLength(8);
    expect(new Set(proofAnchors.map((check) => check.canonical_query_id)).size).toBe(8);
  });

  it("routes reason queries into Shop with Ask Mosaic and complete scalar filters", () => {
    const reason = coreMosaicLabs.find((lab) => lab.stage === "reason");
    expect(reason).toBeDefined();

    const href = retrievalExampleHref(reason!);
    const params = new URLSearchParams(href.split("?", 2)[1]);

    expect(href.startsWith("/catalog?")).toBe(true);
    expect(params.get("ask")).toBe("1");
    expect(params.get("mission")).toBe(reason!.id);
    expect(params.get("q")).toBe(reason!.query);
    Object.entries(reason!.filters).forEach(([key, value]) => {
      if (
        typeof value === "string"
        || typeof value === "number"
        || typeof value === "boolean"
      ) {
        expect(params.get(key)).toBe(String(value));
      }
    });
  });
});
