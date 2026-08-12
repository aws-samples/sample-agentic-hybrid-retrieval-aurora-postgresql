import { describe, expect, it } from "vitest";
import {
  coreMosaicLabs,
  retrievalExampleHref,
  supportingMosaicChecks,
} from "./labMissions";

describe("participant query contract", () => {
  it("keeps eight participant runs inside exactly three required labs", () => {
    const participantChecks = [
      ...coreMosaicLabs,
      ...supportingMosaicChecks.filter((check) => check.core),
    ];

    expect(coreMosaicLabs).toHaveLength(3);
    expect(participantChecks).toHaveLength(8);
    expect(new Set(participantChecks.map((check) => check.canonical_query_id)).size).toBe(8);
  });

  it("routes reason queries to agent mode with their complete filters", () => {
    const reason = coreMosaicLabs.find((lab) => lab.stage === "reason");
    expect(reason).toBeDefined();

    const href = retrievalExampleHref(reason!);
    const params = new URLSearchParams(href.split("?", 2)[1]);

    expect(href.startsWith("/search?")).toBe(true);
    expect(params.get("mode")).toBe("agent");
    expect(params.get("mission")).toBe(reason!.id);
    expect(JSON.parse(params.get("filters")!)).toEqual(reason!.filters);
  });
});
