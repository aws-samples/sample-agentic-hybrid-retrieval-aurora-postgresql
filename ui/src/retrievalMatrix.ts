import { FUSED_LABEL, armLanguage } from "./retrievalLanguage";
import type { ProductSummary, SearchResponse } from "./types";

/**
 * Turns one `/api/search` response into the before/after matrix the Retrieval
 * Playground draws.
 *
 * Everything here is derived from values Aurora returned. The only thing computed
 * in the browser is *which pair of words* explains a fuzzy match, and that pair is
 * shown without a score so no invented number can be mistaken for a measured one.
 * The scores on screen are the ones in `signals`.
 */

export type ArmKey = "fts" | "trigram" | "semantic";
export type ColumnKey = ArmKey | "fusion" | "rerank";

export interface MatrixColumn {
  key: ColumnKey;
  /** What a participant is looking at, in their words. */
  label: string;
  /** The mechanism, in Postgres terms. */
  mechanism: string;
  /** The count that makes this column's contribution legible at a glance. */
  measure: string;
  /** Reads as a sentence after the measure. */
  measureDetail: string;
  sql: string;
}

export interface MatrixCell {
  key: ColumnKey;
  /** Rank as Aurora reported it, or null when the arm never returned this row. */
  rank: number | null;
  /** What the cell shows large. A rank for the arms, a score for the reranker. */
  label: string | null;
  /** The supporting number under it, or null when the label is the only one. */
  detail: string | null;
  /** True when this stage produced nothing for this row. */
  missing: boolean;
}

export interface MatrixRow {
  product: ProductSummary;
  /** Rank once the reranker has spoken. */
  finalRank: number;
  /**
   * Where this row sat among the shown rows *before* reranking.
   *
   * Not `pre_rerank_rank`: that is a position in the fused candidate pool, which
   * is wider than the returned set, so comparing it to `final_rank` would
   * overstate every movement. This is the row's position when the shown rows are
   * ordered by their fused rank, which is the order that would have shipped with
   * the reranker off.
   */
  beforeRank: number;
  /** Positive means the reranker promoted the row. */
  movement: number;
  /** Position in the fused candidate pool, and how big that pool was. */
  fusedRank: number;
  fusedPool: number | null;
  cells: MatrixCell[];
  reasons: MatchReason[];
  /** One sentence naming why this row is in the result set at all. */
  verdict: string;
  isTarget: boolean;
}

export interface MatchReason {
  kind: "lexical" | "fuzzy" | "semantic" | "fusion" | "rerank" | "identity";
  label: string;
}

export interface RetrievalMatrix {
  columns: MatrixColumn[];
  rows: MatrixRow[];
  /** Rows the reranker moved, and the largest single move, both signed. */
  movedRows: number;
  biggestRise: number;
  biggestFall: number;
}

const STOPWORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "how",
  "i", "in", "is", "it", "its", "least", "me", "my", "of", "on", "or", "over",
  "than", "that", "the", "then", "this", "to", "under", "up", "was", "what",
  "which", "with", "without",
]);

/**
 * pg_trgm's own `similarity_threshold` default: the point below which Postgres
 * stops calling two strings similar. Borrowing that boundary rather than picking
 * one keeps the pairs shown here inside the definition the database uses.
 */
const NEAR_MISS_FLOOR = 0.3;

/** More than four repaired words in one chip stops being readable. */
const NEAR_MISS_LIMIT = 4;

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(" ")
    .filter((token) => token.length > 1 && !/^\d+$/.test(token));
}

/**
 * The trigram set pg_trgm compares, using its padding rule.
 *
 * `show_trgm('cat')` is `{"  c"," ca","cat","at "}`: two leading spaces, one
 * trailing. Matching that exactly is what makes the chosen word pair the same
 * pair Postgres scored, rather than a different notion of "close".
 */
export function trigrams(word: string): Set<string> {
  const padded = `  ${word.toLowerCase()} `;
  const grams = new Set<string>();
  for (let index = 0; index + 3 <= padded.length; index += 1) {
    grams.add(padded.slice(index, index + 3));
  }
  return grams;
}

/** pg_trgm `similarity()`: shared trigrams over the union. */
export function trigramSimilarity(left: string, right: string): number {
  if (left === right) return 1;
  const a = trigrams(left);
  const b = trigrams(right);
  let shared = 0;
  a.forEach((gram) => {
    if (b.has(gram)) shared += 1;
  });
  const union = a.size + b.size - shared;
  return union === 0 ? 0 : shared / union;
}

/** The text of a product a participant can actually read on this screen. */
function productWords(product: ProductSummary): string[] {
  const tags = product.tags.filter((tag): tag is string => typeof tag === "string");
  return tokenize(
    [product.title, product.brand, product.model, product.short_description, ...tags]
      .join(" "),
  );
}

function queryWords(query: string): string[] {
  return tokenize(query).filter((token) => !STOPWORDS.has(token));
}

/** Query words that appear verbatim in the fields this screen shows. */
export function sharedWords(query: string, product: ProductSummary): string[] {
  const inProduct = new Set(productWords(product));
  const seen = new Set<string>();
  return queryWords(query).filter((word) => {
    if (!inProduct.has(word) || seen.has(word)) return false;
    seen.add(word);
    return true;
  });
}

export interface NearMiss {
  queryWord: string;
  productWord: string;
}

/**
 * Each misspelled query word paired with the catalog word nearest to it.
 *
 * Returned without scores. The score on screen is the one Aurora computed over the
 * whole document; a second number from a different comparison would only invite
 * the reading that Postgres produced it.
 *
 * Args:
 *   query: The query as it was sent, normalized or raw.
 *   product: A returned product, matched against the fields this screen shows.
 *
 * Returns:
 *   The first few repaired words in query order, so the chip reads as the sentence
 *   the participant typed rather than as a ranked list they have to reassemble.
 */
export function nearMissPairs(query: string, product: ProductSummary): NearMiss[] {
  const catalog = productWords(product);
  const pairs: NearMiss[] = [];
  const seen = new Set<string>();

  for (const word of queryWords(query)) {
    if (pairs.length >= NEAR_MISS_LIMIT) break;
    if (catalog.includes(word) || seen.has(word)) continue;
    seen.add(word);
    let best: { productWord: string; score: number } | null = null;
    for (const candidate of catalog) {
      const score = trigramSimilarity(word, candidate);
      if (score < NEAR_MISS_FLOOR) continue;
      if (!best || score > best.score) best = { productWord: candidate, score };
    }
    if (best) pairs.push({ queryWord: word, productWord: best.productWord });
  }

  return pairs;
}

function formatScore(value: number | null | undefined, digits: number): string | null {
  return value == null ? null : value.toFixed(digits);
}

function armCell(
  key: ColumnKey,
  rank: number | null,
  score: number | null,
  digits: number,
): MatrixCell {
  return {
    key,
    rank,
    label: rank === null ? null : `#${rank}`,
    detail: formatScore(score, digits),
    missing: rank === null,
  };
}

function movementLabel(movement: number): string {
  if (movement > 0) return `Rerank moved it up ${movement}`;
  if (movement < 0) return `Rerank moved it down ${Math.abs(movement)}`;
  return "Rerank kept its place";
}

function reasonsFor(
  product: ProductSummary,
  query: string,
  movement: number,
  rerankApplied: boolean,
): MatchReason[] {
  const signals = product.signals;
  if (!signals) return [];
  const reasons: MatchReason[] = [];
  const shared = sharedWords(query, product);

  if (signals.exact_sku_match) {
    reasons.push({ kind: "identity", label: `Exact SKU ${product.sku}` });
  }
  if (signals.fts.rank !== null) {
    reasons.push({
      kind: "lexical",
      label: shared.length
        ? `Words in this record: ${shared.slice(0, 3).join(", ")}`
        : "Matched indexed text not shown on this card",
    });
  }
  if (signals.trigram.rank !== null) {
    const pairs = nearMissPairs(query, product);
    reasons.push({
      kind: "fuzzy",
      label: pairs.length
        ? `Repaired spelling: ${
          pairs.map((pair) => `${pair.queryWord} to ${pair.productWord}`).join(", ")
        }`
        : "Close spelling somewhere in the record",
    });
  }
  if (signals.semantic.rank !== null && signals.fts.rank === null && signals.trigram.rank === null) {
    reasons.push({
      kind: "semantic",
      label: shared.length
        ? "No arm matched its words; nearest by meaning"
        : "No query word in this record; nearest by meaning",
    });
  }
  if (rerankApplied) {
    reasons.push({ kind: "rerank", label: movementLabel(movement) });
  }
  return reasons;
}

function verdictFor(product: ProductSummary, query: string): string {
  const signals = product.signals;
  if (!signals) return "This row came back without retrieval signals.";
  const arms: string[] = [];
  if (signals.fts.rank !== null) arms.push("exact words");
  if (signals.trigram.rank !== null) arms.push("close spelling");
  if (signals.semantic.rank !== null) arms.push("meaning");
  if (arms.length === 0) {
    return "No candidate arm reported this row, so it needs investigation.";
  }
  if (arms.length === 1 && signals.semantic.rank !== null) {
    const shared = sharedWords(query, product);
    return shared.length
      ? "Only the vector arm found it: its words rank too low for the lexical arms."
      : "Only the vector arm found it: it shares no word with the query.";
  }
  if (arms.length === 1) {
    return `Only the ${arms[0]} arm found it.`;
  }
  return `Found by ${arms.slice(0, -1).join(", ")} and ${arms[arms.length - 1]}.`;
}

const COLUMN_SQL: Record<ColumnKey, string> = {
  fts: `SELECT product_id, fts_rank, fts_score
FROM mosaic_search.search_fts(:query, :filters::jsonb, :fts_limit);`,
  trigram: `SELECT product_id, trigram_rank, trigram_score
FROM mosaic_search.search_trigram(
  :query, :filters::jsonb, :trigram_limit, :trigram_threshold
);`,
  semantic: `SELECT product_id, semantic_rank, semantic_score
FROM mosaic_search.search_vector(
  :query_embedding::vector(1024), :filters::jsonb, :semantic_limit
);`,
  fusion: `SELECT product_id, rrf_score, pre_rerank_rank,
       mosaic_search.reciprocal_rank_contribution(fts_rank, :rrf_k) AS fts_part,
       mosaic_search.reciprocal_rank_contribution(trigram_rank, :rrf_k) AS trigram_part,
       mosaic_search.reciprocal_rank_contribution(semantic_rank, :rrf_k) AS vector_part
FROM mosaic_search.search_hybrid_rrf(
  :query, :query_embedding::vector(1024), :filters::jsonb
)
ORDER BY rrf_score DESC;`,
  rerank: `SELECT product_id, pre_rerank_rank, rerank_score, final_rank
FROM mosaic.search_result_event
WHERE search_event_id = :search_event_id
ORDER BY final_rank;`,
};

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * Build the matrix.
 *
 * Args:
 *   response: A `/api/search` response, live or captured.
 *   targetProductIds: Ids the scenario is validated against, highlighted in place.
 *
 * Returns:
 *   Columns in pipeline order and one row per returned product, ordered by final
 *   rank. Rows whose `signals` are absent are dropped: there is nothing measured
 *   to say about them.
 */
export function buildRetrievalMatrix(
  response: SearchResponse,
  targetProductIds: number[] = [],
): RetrievalMatrix {
  const query = response.normalized_query || response.query;
  const scored = response.results.filter((product) => product.signals);
  const rerankApplied = scored.some((product) => product.signals?.rerank_score != null);

  // The order that would have shipped with the reranker off, restricted to the
  // rows actually shown.
  const beforeOrder = [...scored].sort(
    (left, right) =>
      (left.signals?.pre_rerank_rank ?? 0) - (right.signals?.pre_rerank_rank ?? 0),
  );
  const beforeRankById = new Map(
    beforeOrder.map((product, index) => [product.product_id, index + 1]),
  );

  const profile = response.diagnostics?.retrieval_profile;
  const fusedPool = profile?.fused_limit ?? null;

  const rows: MatrixRow[] = [...scored]
    .sort((left, right) => (left.signals?.final_rank ?? 0) - (right.signals?.final_rank ?? 0))
    .map((product) => {
      const signals = product.signals!;
      const beforeRank = beforeRankById.get(product.product_id) ?? signals.final_rank;
      const movement = beforeRank - signals.final_rank;
      return {
        product,
        finalRank: signals.final_rank,
        beforeRank,
        movement,
        fusedRank: signals.pre_rerank_rank,
        fusedPool,
        cells: [
          armCell("fts", signals.fts.rank, signals.fts.raw_score, 5),
          armCell("trigram", signals.trigram.rank, signals.trigram.raw_score, 3),
          armCell("semantic", signals.semantic.rank, signals.semantic.raw_score, 4),
          // The position in the fused pool, which runs wider than the rows shown.
          // Showing the position among the shown rows here instead would repeat
          // the left half of Before / after and hide where the row really sat.
          armCell("fusion", signals.pre_rerank_rank, signals.rrf_score, 5),
          {
            // The reranker's output is its score. Its rank is already the row's
            // rank badge and the right half of Before / after; printing it a
            // third time would spend the column on nothing.
            key: "rerank" as const,
            rank: signals.rerank_score == null ? null : signals.final_rank,
            label: formatScore(signals.rerank_score, 4),
            detail: null,
            missing: signals.rerank_score == null,
          },
        ],
        reasons: reasonsFor(product, query, movement, rerankApplied),
        verdict: verdictFor(product, query),
        isTarget: targetProductIds.includes(product.product_id),
      };
    });

  const found = (arm: ArmKey) =>
    scored.filter((product) => product.signals?.[arm].rank !== null).length;
  const total = scored.length;
  const moved = rows.filter((row) => row.movement !== 0);
  const movements = rows.map((row) => row.movement);

  const columns: MatrixColumn[] = [
    {
      key: "fts",
      // Labels come from retrievalLanguage so a column heading here and a row in
      // Shop's "Why this match" cannot drift apart; the mechanism line is what
      // this surface adds on top of them.
      label: armLanguage[0].label,
      mechanism: "tsvector + ts_rank_cd",
      measure: `${found("fts")} of ${total}`,
      measureDetail: "rows found",
      sql: COLUMN_SQL.fts,
    },
    {
      key: "trigram",
      label: armLanguage[1].label,
      mechanism: "pg_trgm word_similarity",
      measure: `${found("trigram")} of ${total}`,
      measureDetail: "rows found",
      sql: COLUMN_SQL.trigram,
    },
    {
      key: "semantic",
      label: armLanguage[2].label,
      mechanism: `pgvector HNSW cosine${
        response.diagnostics ? ` · ${response.diagnostics.embedding_dimensions}d` : ""
      }`,
      measure: `${found("semantic")} of ${total}`,
      measureDetail: "rows found",
      sql: COLUMN_SQL.semantic,
    },
    {
      key: "fusion",
      label: FUSED_LABEL,
      // No local default for k. The value lives in db/config/retrieval.yaml and
      // reaches here through the response; inventing a fallback would let this
      // column state a k the run did not use.
      mechanism: profile
        ? `reciprocal rank fusion, k = ${profile.rrf_k}`
        : "reciprocal rank fusion",
      measure: fusedPool ? `${total} of ${fusedPool}` : `${total}`,
      measureDetail: fusedPool ? "fused candidates shown" : "rows ordered",
      sql: COLUMN_SQL.fusion,
    },
    {
      key: "rerank",
      // Not FINAL_LABEL: this cell carries `rerank_score`, and a 0.9204 under a
      // heading that promises a position is the surface lying about its own units.
      // The final position is the row's rank badge and the right half of
      // Before / after.
      label: "Rerank score",
      mechanism: response.diagnostics?.rerank_model_id ?? "cross-encoder rerank",
      measure: rerankApplied ? `${moved.length} of ${total}` : "not applied",
      measureDetail: rerankApplied ? "rows moved" : "order unchanged",
      sql: COLUMN_SQL.rerank,
    },
  ];

  return {
    columns,
    rows,
    movedRows: moved.length,
    biggestRise: movements.length ? Math.max(...movements, 0) : 0,
    biggestFall: movements.length ? Math.min(...movements, 0) : 0,
  };
}

/** The headline sentence above the matrix, built only from what the run reported. */
export function matrixSummary(matrix: RetrievalMatrix): string {
  const [exact, fuzzy, meaning] = matrix.columns;
  const parts = [
    `${exact.label} found ${exact.measure.split(" of ")[0]}`,
    `${fuzzy.label.toLowerCase()} ${fuzzy.measure.split(" of ")[0]}`,
    `${meaning.label.toLowerCase()} ${meaning.measure.split(" of ")[0]}`,
  ];
  const rerank = matrix.movedRows
    ? `Reranking then moved ${plural(matrix.movedRows, "row")}, the largest by ${
      Math.max(matrix.biggestRise, Math.abs(matrix.biggestFall))
    } places.`
    : "Reranking left the fused order unchanged.";
  return `${parts.join(", ")} of the ${matrix.rows.length} rows shown. ${rerank}`;
}
