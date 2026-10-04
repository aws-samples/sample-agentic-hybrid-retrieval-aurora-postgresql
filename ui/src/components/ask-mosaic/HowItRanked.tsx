import { useState } from "react";
import { pickName } from "./comparison";
import {
  receiptCaption,
  receiptLegend,
  rowsFromProducts,
  rowsFromReceipt,
  widestTotal,
  type RankRow,
} from "./rankRows";
import type { ReceiptState } from "./useRankReceipts";
import type { ProductSummary, ToolTraceStep } from "../../types";
import { formatCategoryKey } from "../../format";

export interface RankedSearch {
  runId: string;
  label: string;
  state: ReceiptState;
}

/** One tab per search the answer ran, labelled by the category it searched. */
export function rankedSearches(trace: ToolTraceStep[], states: Record<string, ReceiptState>): RankedSearch[] {
  const searches = trace.filter((step) => step.tool === "search_products" && step.retrieval_run_id);
  return searches.map((step, index) => {
    const category = step.arguments?.category_key;
    return {
      runId: step.retrieval_run_id as string,
      label: typeof category === "string" ? formatCategoryKey(category) : `Search ${index + 1}`,
      state: states[step.retrieval_run_id as string] ?? { status: "loading" },
    };
  });
}

const dash = (rank: number | null) => (rank == null ? "–" : String(rank));

function Bar({ row, widest }: { row: RankRow; widest: number }) {
  const width = (part: number) => `${widest ? (part / widest) * 100 : 0}%`;
  return (
    <span className="ask-rrf-bar" aria-hidden="true">
      <i className="is-fts" style={{ width: width(row.parts.fts) }} />
      <i className="is-trigram" style={{ width: width(row.parts.trigram) }} />
      <i className="is-semantic" style={{ width: width(row.parts.semantic) }} />
    </span>
  );
}

function RankTable({ rows }: { rows: RankRow[] }) {
  const widest = widestTotal(rows);
  return (
    <div className="ask-rank-scroll">
      <table className="ask-rank-table">
        <thead>
          <tr>
            <th scope="col">Final</th>
            <th scope="col">Product</th>
            <th scope="col">Exact</th>
            <th scope="col">Spelling</th>
            <th scope="col">Meaning</th>
            <th scope="col">Split</th>
            <th scope="col">Combined</th>
            <th scope="col">Rerank</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.productId}>
              <th scope="row">{dash(row.final)}</th>
              <td className="ask-rank-name">{row.name ?? <span className="ask-mono">listing {row.productId}</span>}</td>
              <td>{dash(row.fts)}</td>
              <td>{dash(row.trigram)}</td>
              <td>{dash(row.semantic)}</td>
              <td><Bar row={row} widest={widest} /></td>
              <td>{dash(row.combined)}</td>
              <td>{row.rerank != null ? row.rerank.toFixed(3) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Legend() {
  return (
    <p className="ask-rank-key" aria-hidden="true">
      <span><i className="is-fts" />Exact terms</span>
      <span><i className="is-trigram" />Close spelling</span>
      <span><i className="is-semantic" />Meaning</span>
    </p>
  );
}

/**
 * How each search ranked its products: the position every retrieval method gave
 * it, what each added to the combined score, and where reranking put it. Rows
 * come from the saved search; if that cannot be read, the recommended products'
 * own signals stand in and the heading says so.
 */
export function HowItRanked({
  searches,
  products,
  names,
}: {
  searches: RankedSearch[];
  products: ProductSummary[];
  names: Map<number, string>;
}) {
  const [picked, setPicked] = useState(0);
  const current = searches[Math.min(picked, searches.length - 1)];
  if (!current) return null;
  const state = current.state;
  const fallback = state.status === "error" || state.status === "loading";
  const rows = state.status === "ready"
    ? rowsFromReceipt(state.receipt, names)
    : rowsFromProducts(products, pickName);
  return (
    <section className="ask-rank" aria-label="How it ranked">
      <div className="ask-rank-head">
        <h4>How it ranked</h4>
        <div className="ask-rank-tabs" role="group" aria-label="Searches">
          {searches.map((search, index) => (
            <button
              key={search.runId}
              type="button"
              className="ask-chip"
              aria-pressed={index === picked}
              onClick={() => setPicked(index)}
            >
              {search.label}
            </button>
          ))}
        </div>
      </div>
      <Legend />
      {state.status === "ready" ? <p className="ask-rank-note">{receiptLegend(state.receipt)}</p> : null}
      {rows.length ? <RankTable rows={rows} /> : null}
      <p className="ask-rank-note" role="status">
        {state.status === "ready"
          ? receiptCaption(current.runId, state.receipt)
          : fallback && state.status === "loading"
            ? "Reading the saved search…"
            : "Ranks for the recommended products. The saved search could not be read."}
      </p>
    </section>
  );
}
