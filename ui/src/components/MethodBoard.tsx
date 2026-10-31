import type { CSSProperties, ReactNode } from "react";
import { productImage } from "../media";
import { RankMove } from "./RankMove";
import { armLabel, armPoolKey, type RetrievalArm } from "../retrievalLanguage";
import type { ProductSummary, SearchResponse } from "../types";
import "../method-board.css";

const BOARD_ROWS = 5;

type Column = {
  key: "fts" | "fuzzy" | "semantic" | "combined" | "reranked";
  title: string;
  /** The SQL function the lab guides call for this stage, when one runs in Aurora. */
  fn?: string;
  engine: string;
  meta: string;
  /** How many of this search's matches reached the shortlist, for a search column. */
  reached?: number;
  accent: "retrieve" | "rank" | "done";
  /** This column's own rank for a product, or null when it did not rank it. */
  rankOf: (product: ProductSummary) => number | null;
  /**
   * The earlier stage this column's movement is measured against, with its own
   * words: the best single search for Combined, the combined position for Reranked.
   */
  previous?: { label: string; rank: (product: ProductSummary) => number | null };
};

/** The product's best (smallest) rank across the three searches, or null when none ranked it. */
function bestSearchRank(product: ProductSummary): number | null {
  const ranks = (["fts", "fuzzy", "semantic"] as const)
    .map((arm) => product.signals?.[arm]?.rank ?? null)
    .filter((rank): rank is number => rank !== null);
  return ranks.length ? Math.min(...ranks) : null;
}

const ARM_ENGINE: Record<RetrievalArm, string> = {
  fts: "tsvector and ts_rank_cd",
  fuzzy: "pg_trgm",
  semantic: "pgvector HNSW index",
};

/** The functions participants call by name in psql, so a card and the terminal agree. */
const ARM_FUNCTION: Record<RetrievalArm, string> = {
  fts: "search_fts",
  fuzzy: "search_fuzzy",
  semantic: "search_semantic",
};

function columnsFor(response: SearchResponse): Column[] {
  const diagnostics = response.diagnostics;
  const counts = diagnostics?.candidate_counts ?? {};
  const pool = counts.fused_pool;
  const k = diagnostics?.retrieval_profile?.rrf_k;
  const reranked = diagnostics?.rerank_status === "applied";
  // A search's count is how many of its matches reached the shortlist, not a position.
  const reached = (count: number | undefined) =>
    count === undefined ? "" : count === 1 ? "1 match reached the shortlist" : `${count} of its matches reached the shortlist`;
  const arms: Column[] = (["fts", "fuzzy", "semantic"] as const).map((arm) => ({
    key: arm,
    title: armLabel[arm],
    fn: ARM_FUNCTION[arm],
    engine: ARM_ENGINE[arm],
    meta: reached(counts[armPoolKey[arm]]),
    reached: counts[armPoolKey[arm]],
    accent: "retrieve",
    rankOf: (product) => product.signals?.[arm]?.rank ?? null,
  }));
  return [
    ...arms,
    {
      key: "combined",
      title: "Combined (RRF)",
      fn: "search_hybrid_rrf",
      engine: typeof k === "number" ? `k = ${k}` : "RRF",
      meta: pool === undefined ? "" : `Shortlist of ${pool}`,
      accent: "rank",
      rankOf: (product) => product.signals?.pre_rerank_rank ?? null,
      previous: { label: "Search", rank: bestSearchRank },
    },
    {
      key: "reranked",
      title: reranked ? "Reranked" : "Not reranked",
      engine: reranked ? "Cohere Rerank" : "final order is the combined order",
      meta: reranked && pool !== undefined ? `Reordered all ${pool}` : "",
      accent: reranked ? "done" : "rank",
      rankOf: (product) => product.signals?.final_rank ?? null,
      previous: reranked
        ? { label: "Combined", rank: (product) => product.signals?.pre_rerank_rank ?? null }
        : undefined,
    },
  ];
}

type Tier = "target" | "lower" | "unranked";

/**
 * Each search method's own top five on the search's shortlist.
 *
 * Shared by Shop and the Playground. Every rank printed is the product's real
 * rank in that method, read from `signals`, never a renumbered position. With
 * `pool`, the shortlist products read from the search's saved receipts, a method
 * whose matches all ranked below the page still lists them, faded; without it
 * the board ranks only the products shown and says so. `targetRank` is the last
 * rank the lab counts as found (the manifest's bound), so the wanted product's
 * badge is green inside it and orange past it.
 */
export function MethodBoard({
  response, pool = null, wantedId = null, wantedName, targetRank, images, onSelect, only, reads,
}: {
  response: SearchResponse;
  /** The shortlist products each column draws from (`useShortlist`); the products shown when null. */
  pool?: ProductSummary[] | null;
  /** What each search looked for, shown above what it found. */
  reads?: Partial<Record<RetrievalArm, ReactNode>>;
  /** The columns to show, in board order; all five when absent. */
  only?: ReadonlyArray<Column["key"]>;
  wantedId?: number | null;
  /** Names the wanted product in the note when this search did not return it. */
  wantedName?: string;
  /** The last rank that counts as the wanted product's target. */
  targetRank?: number;
  images: Map<number, string>;
  onSelect?: (productId: number) => void;
}) {
  const columns = columnsFor(response).filter((column) => !only || only.includes(column.key));
  const candidates = pool ?? response.results;
  const shownIds = new Set(response.results.map((product) => product.product_id));
  const shown = response.results.length;
  const shortlist = response.diagnostics?.candidate_counts?.fused_pool;
  const wanted = wantedId === null ? undefined
    : candidates.find((product) => product.product_id === wantedId);
  const wantedMissing = wantedId !== null && !wanted;
  const name = wantedName ?? "wanted product";
  // The product the search put first, followed across every column it appears in.
  const topId = candidates.find((product) => product.signals?.final_rank === 1)?.product_id ?? null;
  // Header, badge and list are rows of one grid, so they line up across the columns.
  const parts = wanted ? 3 : 2;
  const note = pool
    ? wantedMissing
      ? `The ${name} is not on the shortlist of ${shortlist}.`
      : `Each method’s own top five on the shortlist of ${shortlist}. Faded rows are not among the ${shown} shown.${wanted ? " Green marks the lab’s product." : ""}`
    : wantedMissing
      ? `The ${name} is not among the ${shown} shown.`
      : `The ${shown} shown, at each method’s own rank.${wanted ? " Green marks the lab’s product." : ""}`;

  const badge = (column: Column): { tier: Tier; text: string } | null => {
    if (!wanted) return null;
    const rank = column.rankOf(wanted);
    if (rank === null) return { tier: "unranked", text: "Wanted product: not found here" };
    const inside = targetRank === undefined || rank <= targetRank;
    return { tier: inside ? "target" : "lower", text: `Wanted #${rank}` };
  };

  return (
    <section className="method-board" aria-label="Each method's top five">
      <header className="method-board-head">
        <h3>Each method’s top five</h3>
        <p>{note}</p>
      </header>
      <div className="method-columns" style={{ "--board-columns": columns.length, "--board-parts": parts } as CSSProperties}>
        {columns.map((column, index) => {
          const rows = candidates
            .map((product) => ({ product, rank: column.rankOf(product) }))
            .filter((row): row is { product: ProductSummary; rank: number } => row.rank !== null)
            .sort((a, b) => a.rank - b.rank)
            .slice(0, BOARD_ROWS);
          const mark = badge(column);
          return (
            <article
              className="method-column"
              data-method={column.key}
              data-accent={column.accent}
              style={{ "--i": index } as CSSProperties}
              key={column.key}
            >
              <header>
                <h4>{column.title}</h4>
                <p className="method-engine">{column.fn ? <code>{column.fn}</code> : null}{column.engine}</p>
                {reads && column.key in reads ? <p className="method-reads" aria-label={`${column.title} reads the request as`}>{reads[column.key as RetrievalArm]}</p> : null}
                {column.meta ? <p className="method-meta">{column.meta}</p> : null}
              </header>
              {mark ? <p className="method-badge" data-tier={mark.tier}>{mark.text}</p> : null}
              {rows.length ? (
                <ol className="method-list">
                  {rows.map(({ product, rank }) => {
                    const earlier = column.previous?.rank(product);
                    const isWanted = product.product_id === wantedId;
                    const isTop = product.product_id === topId && !isWanted;
                    const onPage = shownIds.has(product.product_id);
                    const final = product.signals?.final_rank;
                    const content = (
                      <>
                        <span className="method-rank">{rank}</span>
                        <img
                          src={images.get(product.product_id) ?? productImage(product)}
                          alt=""
                          width={36}
                          height={36}
                          loading="lazy"
                          decoding="async"
                        />
                        <span className="method-text">
                          <span className="method-title">{product.title}</span>
                          {onPage ? null : <span className="sr-only">, not on this page</span>}
                          {column.previous && earlier !== undefined ? (
                            <span className="method-move">
                              {earlier === null ? null : (
                                <span className="method-from"><span>{column.previous.label}</span> #{earlier}</span>
                              )}
                              <RankMove from={earlier} to={rank} />
                            </span>
                          ) : column.reached !== undefined && final !== undefined ? (
                            <span className="method-move"><span className="method-from"><span>Final</span> #{final}</span></span>
                          ) : <span className="method-move" aria-hidden="true" />}
                        </span>
                      </>
                    );
                    return (
                      <li className="method-row" data-target={isWanted || undefined} data-top={isTop || undefined} data-off-page={!onPage || undefined} key={product.product_id}>
                        {onSelect && onPage ? (
                          <button
                            type="button"
                            aria-label={`${product.title}, ${column.title} rank ${rank}`}
                            onClick={() => onSelect(product.product_id)}
                          >{content}</button>
                        ) : <div className="method-row-body">{content}</div>}
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className="method-empty">
                  {pool
                    ? "None on the shortlist"
                    : column.reached
                      ? `Its ${column.reached} on the shortlist ranked below the ${shown} shown`
                      : `None of the ${shown} shown`}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
