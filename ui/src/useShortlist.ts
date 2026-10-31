import { useEffect, useState } from "react";
import { api } from "./api";
import type { ProductSummary, RankSignal, SearchResponse, SearchResultEventRecord } from "./types";

/** Rows per method on the board; the board's own limit. */
const TOP = 5;

const ARM_RANK = {
  fts: "fts_rank",
  fuzzy: "fuzzy_rank",
  semantic: "semantic_rank",
} as const;

/** The first `top` receipts by one rank, skipping receipts that rank lacks. */
function firstBy(receipts: SearchResultEventRecord[], rank: (row: SearchResultEventRecord) => number | null, top: number) {
  return receipts
    .filter((row) => rank(row) !== null)
    .sort((a, b) => (rank(a) as number) - (rank(b) as number))
    .slice(0, top)
    .map((row) => row.product_id);
}

/**
 * The shortlist products a board of each method's top five needs: every
 * search's first five, the combined order's, the final order's, and the wanted
 * product when the shortlist holds it.
 */
export function boardProductIds(receipts: SearchResultEventRecord[], wantedId: number | null, top = TOP): number[] {
  const ids = new Set<number>([
    ...firstBy(receipts, (row) => row.fts_rank, top),
    ...firstBy(receipts, (row) => row.fuzzy_rank, top),
    ...firstBy(receipts, (row) => row.semantic_rank, top),
    ...firstBy(receipts, (row) => row.fused_rank, top),
    ...firstBy(receipts, (row) => row.result_rank, top),
  ]);
  if (wantedId !== null && receipts.some((row) => row.product_id === wantedId)) ids.add(wantedId);
  return [...ids];
}

function score(receipt: SearchResultEventRecord, key: string): number | null {
  const value = receipt.scores?.[key];
  return typeof value === "number" ? value : null;
}

/** A product not on the page, ranked as its saved receipt records it. */
export function fromReceipt(product: ProductSummary, receipt: SearchResultEventRecord, semantics: string): ProductSummary {
  const arm = (key: keyof typeof ARM_RANK): RankSignal => ({
    rank: receipt[ARM_RANK[key]],
    raw_score: score(receipt, key),
    rrf_contribution: null,
  });
  return {
    ...product,
    signals: {
      fts: arm("fts"),
      fuzzy: arm("fuzzy"),
      semantic: arm("semantic"),
      rrf_score: score(receipt, "rrf") ?? 0,
      pre_rerank_rank: receipt.fused_rank ?? receipt.result_rank,
      pre_rerank_score: score(receipt, "pre_rerank") ?? 0,
      rerank_score: score(receipt, "rerank"),
      rerank_rank: receipt.rerank_rank,
      final_rank: receipt.result_rank,
      score_semantics: semantics,
    },
  };
}

/**
 * The products each method's top `top` draws from on the search's saved shortlist.
 *
 * Reads the receipts the search wrote to Aurora, so a method whose matches all
 * ranked below the page still shows them, then loads each listed product that
 * is not on the page. Products on the page keep the response's own copy.
 * Returns null while loading and when the shortlist cannot be read; the board
 * then ranks only the products shown, and says so.
 */
export function useShortlist(
  response: SearchResponse | null | undefined, wantedId: number | null, top = TOP,
): ProductSummary[] | null {
  const [pool, setPool] = useState<{ key: string; products: ProductSummary[] } | null>(null);
  const searchEventId = response?.search_event_id ?? null;
  const key = `${searchEventId}:${wantedId}:${top}`;

  useEffect(() => {
    if (!response || !searchEventId) return;
    let current = true;
    (async () => {
      const { candidates } = await api.retrievalEvent(searchEventId);
      const shown = new Map(response.results.map((product) => [product.product_id, product]));
      const ids = boardProductIds(candidates, wantedId, top);
      const missing = ids.filter((id) => !shown.has(id));
      const loaded = new Map((await Promise.all(missing.map((id) => api.product(id)))).map((product) => [product.product_id, product]));
      const semantics = response.results[0]?.signals?.score_semantics ?? "";
      const receipts = new Map(candidates.map((row) => [row.product_id, row]));
      return ids.map((id) => shown.get(id) ?? fromReceipt(loaded.get(id) as ProductSummary, receipts.get(id) as SearchResultEventRecord, semantics));
    })()
      .then((products) => { if (current) setPool({ key, products }); })
      .catch((error: unknown) => {
        console.warn(`Each method's top five: could not read the shortlist of search ${searchEventId}; showing the products on the page.`, error);
      });
    return () => { current = false; };
  }, [response, searchEventId, wantedId, top, key]);

  return pool?.key === key ? pool.products : null;
}
