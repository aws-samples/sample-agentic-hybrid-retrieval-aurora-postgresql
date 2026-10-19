import type { CSSProperties } from "react";
import { productImage } from "../media";
import { RankMove } from "./RankMove";
import { armLabel, armPoolKey, type RetrievalArm } from "../retrievalLanguage";
import type { ProductSummary, SearchResponse } from "../types";
import "../method-board.css";

const BOARD_ROWS = 5;

type Column = {
  key: "fts" | "trigram" | "semantic" | "combined" | "reranked";
  title: string;
  engine: string;
  meta: string;
  accent: "retrieve" | "rank";
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
  const ranks = (["fts", "trigram", "semantic"] as const)
    .map((arm) => product.signals?.[arm]?.rank ?? null)
    .filter((rank): rank is number => rank !== null);
  return ranks.length ? Math.min(...ranks) : null;
}

const ARM_ENGINE: Record<RetrievalArm, string> = {
  fts: "tsvector · ts_rank_cd",
  trigram: "pg_trgm",
  semantic: "pgvector · HNSW",
};

function columnsFor(response: SearchResponse): Column[] {
  const diagnostics = response.diagnostics;
  const counts = diagnostics?.candidate_counts ?? {};
  const pool = counts.fused_pool;
  const k = diagnostics?.retrieval_profile?.rrf_k;
  const reranked = diagnostics?.rerank_status === "applied";
  // A search's count is how many of its matches reached the combined pool, not a position.
  const reached = (count: number | undefined) =>
    count === undefined ? "" : count === 1 ? "1 match reached the pool" : `${count} of its matches reached the pool`;
  const arms: Column[] = (["fts", "trigram", "semantic"] as const).map((arm) => ({
    key: arm,
    title: armLabel[arm],
    engine: ARM_ENGINE[arm],
    meta: reached(counts[armPoolKey[arm]]),
    accent: "retrieve",
    rankOf: (product) => product.signals?.[arm]?.rank ?? null,
  }));
  return [
    ...arms,
    {
      key: "combined",
      title: "Combined in Aurora",
      engine: typeof k === "number" ? `RRF, k = ${k}` : "RRF",
      meta: pool === undefined ? "" : `Pool of ${pool}`,
      accent: "rank",
      rankOf: (product) => product.signals?.pre_rerank_rank ?? null,
      previous: { label: "search", rank: bestSearchRank },
    },
    {
      key: "reranked",
      title: reranked ? "Reranked" : "Not reranked",
      engine: reranked ? "Cohere Rerank" : "final order is the combined order",
      meta: reranked && pool !== undefined ? `Reordered all ${pool}` : "",
      accent: "rank",
      rankOf: (product) => product.signals?.final_rank ?? null,
      previous: reranked
        ? { label: "combined", rank: (product) => product.signals?.pre_rerank_rank ?? null }
        : undefined,
    },
  ];
}

type Tier = "target" | "lower" | "unranked";

/**
 * Each search method's own top five among the products a search returned.
 *
 * Shared by Shop and the Playground. Every rank printed is the product's real
 * rank in that method, read from `signals`, never a renumbered position, and the
 * rows are limited to the returned products: nothing here fetches the wider
 * pool. `targetRank` is the last rank the lab counts as found (the manifest's
 * bound), so the wanted product's badge is green inside it and orange past it.
 */
export function MethodBoard({
  response, wantedId = null, wantedName, targetRank, images, onSelect, only,
}: {
  response: SearchResponse;
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
  const wanted = wantedId === null ? undefined
    : response.results.find((product) => product.product_id === wantedId);
  const wantedMissing = wantedId !== null && !wanted;
  const name = wantedName ?? "wanted product";
  // The product the search put first, followed across every column it appears in.
  const topId = response.results.find((product) => product.signals?.final_rank === 1)?.product_id ?? null;

  const badge = (column: Column): { tier: Tier; text: string } | null => {
    if (!wanted) return null;
    const rank = column.rankOf(wanted);
    if (rank === null) return { tier: "unranked", text: "Not ranked by this search" };
    const inside = targetRank === undefined || rank <= targetRank;
    return { tier: inside ? "target" : "lower", text: `Wanted #${rank}` };
  };

  return (
    <section className="method-board" aria-label="Each method's top five">
      <header className="method-board-head">
        <h3>Each method’s top five</h3>
        <p>
          {wantedMissing
            ? `The ${name} was not returned by this search. Among the ${response.results.length} products it did return, each is at its own rank.`
            : wanted
              ? `Highlighted: the product this lab is looking for. Among the ${response.results.length} products this search returned, each at its own rank.`
              : `Among the ${response.results.length} products this search returned, each at its own rank.`}
        </p>
      </header>
      <div className="method-columns" style={{ "--board-columns": columns.length } as CSSProperties}>
        {columns.map((column, index) => {
          const rows = response.results
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
                <p className="method-engine">{column.engine}</p>
                {column.meta ? <p className="method-meta">{column.meta}</p> : null}
              </header>
              {mark ? <p className="method-badge" data-tier={mark.tier}>{mark.text}</p> : null}
              {rows.length ? (
                <ol className="method-list">
                  {rows.map(({ product, rank }) => {
                    const earlier = column.previous?.rank(product);
                    const isWanted = product.product_id === wantedId;
                    const isTop = product.product_id === topId && !isWanted;
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
                          {column.previous && earlier !== undefined ? (
                            <span className="method-move">
                              {earlier === null ? null : `from ${column.previous.label} #${earlier} `}
                              <RankMove from={earlier} to={rank} />
                            </span>
                          ) : null}
                        </span>
                      </>
                    );
                    return (
                      <li className="method-row" data-target={isWanted || undefined} data-top={isTop || undefined} key={product.product_id}>
                        {onSelect ? (
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
              ) : <p className="method-empty">None of the returned products</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
