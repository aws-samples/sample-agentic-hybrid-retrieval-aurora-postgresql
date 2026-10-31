// @vitest-environment jsdom

import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { seedRun } from "./retrievalSeed";
import type { ProductDetail, SearchResultEventRecord } from "./types";
import { boardProductIds, useShortlist } from "./useShortlist";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function receipt(productId: number, ranks: Partial<SearchResultEventRecord>): SearchResultEventRecord {
  return {
    product_id: productId, result_rank: 50, fts_rank: null, fuzzy_rank: null, semantic_rank: null,
    fused_rank: null, rerank_rank: null, scores: {}, provenance: {}, ...ranks,
  };
}

describe("boardProductIds", () => {
  it("takes each order's first five and the wanted product the shortlist holds", () => {
    const receipts = Array.from({ length: 20 }, (_, index) =>
      receipt(index + 1, { semantic_rank: index + 1, fused_rank: index + 1, result_rank: index + 1 }));
    receipts.push(receipt(90, { fuzzy_rank: 1, fused_rank: 30, result_rank: 30 }));
    expect(boardProductIds(receipts, 18).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 18, 90]);
    expect(boardProductIds(receipts, 999)).not.toContain(999);
  });
});

describe("useShortlist", () => {
  it("keeps the page's own products and ranks the rest from their saved receipts", async () => {
    const shown = seedRun.results.slice(0, 2);
    const response = { ...seedRun, results: shown };
    const below = { ...structuredClone(seedRun.results[0]), product_id: 777, title: "Below the page", signals: null } as ProductDetail;
    vi.spyOn(api, "retrievalEvent").mockResolvedValue({
      run: {} as never,
      candidates: [
        receipt(shown[0].product_id, { semantic_rank: 1, fused_rank: 1, result_rank: 1 }),
        receipt(shown[1].product_id, { semantic_rank: 2, fused_rank: 2, result_rank: 2 }),
        receipt(777, { fuzzy_rank: 1, fused_rank: 9, rerank_rank: 14, result_rank: 14, scores: { fuzzy: 0.4 } }),
      ],
    });
    const product = vi.spyOn(api, "product").mockResolvedValue(below);
    const { result } = renderHook(() => useShortlist(response, null));
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(product).toHaveBeenCalledTimes(1);
    expect(product).toHaveBeenCalledWith(777);
    expect(result.current!.filter((item) => shown.includes(item))).toHaveLength(2);
    const loaded = result.current!.find((item) => item.product_id === 777)!;
    expect(loaded.signals).toMatchObject({
      fuzzy: { rank: 1, raw_score: 0.4 }, fts: { rank: null }, pre_rerank_rank: 9, final_rank: 14,
    });
  });

  it("stays null when the saved shortlist cannot be read, so the board ranks the page", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(api, "retrievalEvent").mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useShortlist(seedRun, null));
    await waitFor(() => expect(warn).toHaveBeenCalled());
    expect(result.current).toBeNull();
    expect(String(warn.mock.calls[0][0])).toContain(seedRun.search_event_id);
  });
});
