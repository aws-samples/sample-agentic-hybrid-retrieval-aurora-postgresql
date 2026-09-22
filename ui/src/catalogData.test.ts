import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { createCatalogData, type BrowseRequest } from "./catalogData";
import type { CatalogPage } from "./types";

vi.mock("./api", () => ({ api: { catalog: vi.fn() } }));
const input: BrowseRequest = { dataset: "real-v1", filters: {}, offset: 0, sort: "featured", collection: "workspace" };
const page: CatalogPage = { total: 120, offset: 0, limit: 12, products: [], facets: { domain: [], category_key: [], brand: [], availability: [] } };

describe("catalog browse reuse", () => {
  beforeEach(() => { vi.mocked(api.catalog).mockReset().mockResolvedValue(page); });
  afterEach(() => { vi.useRealTimers(); });

  it("shares concurrent page reads and reuses a return visit", async () => {
    const data = createCatalogData();
    await Promise.all([data.load(input), data.load(input)]);
    expect(await data.load(input)).toEqual(page);
    expect(api.catalog).toHaveBeenCalledTimes(1);
  });

  it("keeps filters, ordering, page size, collection and catalog identity separate", async () => {
    const data = createCatalogData();
    for (const request of [input, { ...input, offset: 12 }, { ...input, sort: "rating" },
      { ...input, limit: 24 }, { ...input, dataset: "real-v2" }, { ...input, collection: "all" as const },
      { ...input, filters: { attributes: { Color: "Black" } } },
      { ...input, filters: { attributes: { Color: "White" } } }]) {
      await data.load(request);
    }
    expect(api.catalog).toHaveBeenCalledTimes(8);
  });

  it("expires saved pages and does not preserve a failed request", async () => {
    vi.useFakeTimers();
    const data = createCatalogData();
    vi.mocked(api.catalog).mockRejectedValueOnce(new Error("offline"));
    await expect(data.load(input)).rejects.toThrow("offline");
    expect(data.peek(input)).toBeUndefined();
    await data.load(input);
    vi.advanceTimersByTime(60_001);
    expect(data.peek(input)).toBeUndefined();
    await data.load(input);
    expect(api.catalog).toHaveBeenCalledTimes(3);
  });

  it("bounds retained pages and evicts the oldest page", async () => {
    const data = createCatalogData();
    for (let index = 0; index < 33; index += 1) await data.load({ ...input, offset: index * 12 });
    expect(data.peek(input)).toBeUndefined();
    await data.load(input);
    expect(api.catalog).toHaveBeenCalledTimes(34);
  });
});
