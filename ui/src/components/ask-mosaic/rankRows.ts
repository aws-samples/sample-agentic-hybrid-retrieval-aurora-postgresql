import type { ProductSummary, RetrievalRunResponse, SearchResultEventRecord } from "../../types";
import { formatDuration } from "./findings";

/** What each retrieval method added to a product's combined score, as recorded. */
export interface ChannelParts {
  fts: number;
  trigram: number;
  semantic: number;
}

export interface RankRow {
  productId: number;
  /** Null until the product's name is known; the table then prints its listing id. */
  name: string | null;
  final: number | null;
  combined: number | null;
  fts: number | null;
  trigram: number | null;
  semantic: number | null;
  rerank: number | null;
  parts: ChannelParts;
}

export const ROW_LIMIT = 5;

const asNumber = (value: unknown): number | null => (typeof value === "number" ? value : null);

function recordedContribution(provenance: Record<string, unknown>, channel: string): number {
  const channels = provenance.channels as Record<string, { rrf_contribution?: unknown }> | undefined;
  return asNumber(channels?.[channel]?.rrf_contribution) ?? 0;
}

/**
 * The first rows of a saved search's receipt, in final order. Ranks and
 * contributions are the ones the database wrote while it fused; nothing is
 * recomputed here, so the bars cannot disagree with the fusion that ran.
 */
export function rowsFromReceipt(
  receipt: RetrievalRunResponse,
  names: Map<number, string>,
  limit = ROW_LIMIT,
): RankRow[] {
  return [...receipt.candidates]
    .filter((row: SearchResultEventRecord) => row.eligible !== false)
    .sort((left, right) => left.result_rank - right.result_rank)
    .slice(0, limit)
    .map((row) => ({
      productId: row.product_id,
      name: names.get(row.product_id) ?? null,
      final: row.result_rank,
      combined: row.fused_rank,
      fts: row.fts_rank,
      trigram: row.trigram_rank,
      semantic: row.semantic_rank,
      rerank: asNumber(row.scores?.rerank),
      parts: {
        fts: recordedContribution(row.provenance ?? {}, "fts"),
        trigram: recordedContribution(row.provenance ?? {}, "trigram"),
        semantic: recordedContribution(row.provenance ?? {}, "vector"),
      },
    }));
}

/** The recommended products' own signals, when the saved search cannot be read. */
export function rowsFromProducts(products: ProductSummary[], name: (product: ProductSummary) => string): RankRow[] {
  return products.flatMap((product) => {
    const signals = product.signals;
    if (!signals) return [];
    return [{
      productId: product.product_id,
      name: name(product),
      final: signals.final_rank,
      combined: signals.pre_rerank_rank,
      fts: signals.fts.rank,
      trigram: signals.trigram.rank,
      semantic: signals.semantic.rank,
      rerank: signals.rerank_score,
      parts: {
        fts: signals.fts.rrf_contribution ?? 0,
        trigram: signals.trigram.rrf_contribution ?? 0,
        semantic: signals.semantic.rrf_contribution ?? 0,
      },
    }];
  });
}

/** The largest combined score among the rows, which the widest bar spans. */
export function widestTotal(rows: RankRow[]): number {
  return Math.max(0, ...rows.map((row) => row.parts.fts + row.parts.trigram + row.parts.semantic));
}

/** "Search cc3a32d8 · 3.5 s in the service · combined 50 from exact terms 1, close spelling 36, meaning 38". */
export function receiptCaption(runId: string, receipt: RetrievalRunResponse): string {
  const { run } = receipt;
  const counts = run.candidate_counts ?? {};
  const pool = counts.fused_pool;
  return [
    `Search ${runId.slice(0, 8)}`,
    run.total_latency_ms != null ? `${formatDuration(run.total_latency_ms)} in the service` : null,
    pool != null
      ? `combined ${pool} from exact terms ${counts.fts_in_pool ?? 0}, close spelling ${counts.trigram_in_pool ?? 0}, meaning ${counts.semantic_in_pool ?? 0}`
      : null,
  ].filter(Boolean).join(" · ");
}

/** "RRF, k = 60 · rerank model id": the settings this search recorded about itself. */
export function receiptLegend(receipt: RetrievalRunResponse): string {
  const k = asNumber(receipt.run.retrieval_profile?.rrf_k);
  return [
    k != null ? `RRF, k = ${k}` : null,
    receipt.run.rerank_model_id ? `rerank ${receipt.run.rerank_model_id}` : null,
  ].filter(Boolean).join(" · ");
}
