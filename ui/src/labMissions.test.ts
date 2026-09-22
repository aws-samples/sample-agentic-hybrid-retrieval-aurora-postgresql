import { describe, expect, it } from "vitest";
import { forwardedSearchFilters } from "./navigation";
import {
  coreMosaicLabs,
  mosaicLabManifest,
  pipelineRequests,
  resolvePipelineRequests,
  retrievalExampleHref,
  shopMissionHref,
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

  it("preserves the mission address when targeting the result list directly", () => {
    // A result-list target must retain the scenario link's question and gates.
    const reason = coreMosaicLabs.find((lab) => lab.stage === "reason");
    expect(reason).toBeDefined();

    const chip = shopMissionHref(reason!, { view: "results" });
    const card = retrievalExampleHref(reason!);
    expect(chip.split("?", 1)[0]).toBe(card.split("?", 1)[0]);

    const chipParams = new URLSearchParams(chip.split("?", 2)[1]);
    expect(chipParams.get("view")).toBe("results");
    chipParams.delete("view");
    const cardParams = new URLSearchParams(card.split("?", 2)[1]);
    chipParams.sort();
    cardParams.sort();
    expect(chipParams.toString()).toBe(cardParams.toString());
  });

  it("carries the ranking mission's full filter set into Shop", () => {
    const rank = coreMosaicLabs.find((lab) => lab.stage === "rank");
    expect(rank!.filters.category_key).toBe("monitor");

    const params = new URLSearchParams(
      shopMissionHref(rank!, { view: "results" }).split("?", 2)[1],
    );

    expect(forwardedSearchFilters(params)).toEqual(rank!.filters);
    expect(params.get("mission")).toBe(rank!.id);
    expect(params.get("q")).toBe(rank!.query);
    expect(params.get("domain")).toBe("consumer_electronics");
    expect(params.get("category_key")).toBe("monitor");
    // Only the reasoning lab asks the agent a question.
    expect(params.get("ask")).toBeNull();
  });
});

it("resolves the multi-part Pipeline request from the canonical mission and rejects a broken reference", () => {
  const mission = coreMosaicLabs.find((lab) => lab.id === "agentic-research")!;
  const request = pipelineRequests.find((item) => item.id === "plan-workspace")!;
  expect(request.query).toBe(mission.query);
  expect(request.filters).toBe(mission.filters);
  const changed = structuredClone(mosaicLabManifest);
  changed.missions.find((lab) => lab.id === mission.id)!.query = "An updated two-part request";
  expect(resolvePipelineRequests(changed).find((item) => item.id === request.id)?.query).toBe("An updated two-part request");
  changed.missions = changed.missions.filter((lab) => lab.id !== mission.id);
  expect(() => resolvePipelineRequests(changed)).toThrow(/Unknown Playground mission/);
});


describe("Shop example references", () => {
  it("keeps queries and filters tied to their source and covers all three needs", async () => {
    const { shopSearchExamples, mosaicLabManifest } = await import("./labMissions");
    const requests = [...mosaicLabManifest.missions, ...mosaicLabManifest.supporting_checks, ...mosaicLabManifest.playground.requests];
    expect(new Set(shopSearchExamples.map(item => item.kind))).toEqual(new Set(["Keywords", "Typo", "Intent"]));
    expect(new Set(shopSearchExamples.map(item => item.filters.category_key))).toEqual(new Set(["headphones", "monitor", "chair"]));
    for (const example of shopSearchExamples) {
      const request = requests.find(item => item.id === example.reference_id)!;
      expect(example.query).toBe(request.query);
      expect(example.filters).toEqual(request.filters);
    }
  });
  it("rejects a sample with no source request", async () => {
    const { resolveShopExamples, mosaicLabManifest } = await import("./labMissions");
    const changed = structuredClone(mosaicLabManifest);
    changed.playground.shop_examples[0].reference_id = "missing";
    expect(() => resolveShopExamples(changed)).toThrow("Unknown Shop example");
  });
});
