import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useMemo, useState } from "react";
import { CodeBlock } from "../components/CodeBlock";
import type { MosaicLabMission } from "../labMissions";
import { productImageMap } from "../media";
import {
  buildRetrievalMatrix,
  matrixSummary,
  type ColumnKey,
  type MatrixRow,
} from "../retrievalMatrix";
import { seedProvenance, seedRunFor } from "../retrievalSeed";
import type { SearchResponse } from "../types";

/**
 * The Retrieval Observatory: five retrievers, one row per result, side by side.
 *
 * The point of this surface is a comparison, and a comparison has to be visible
 * all at once. The version this replaces showed one retriever at a time behind a
 * tab strip, so eleven of twelve rows read as an empty column and the difference
 * between "found by exact words" and "found by meaning" never appeared on screen.
 * Reading it required clicking five tabs and remembering what the last one said.
 *
 * So the arms are columns and the results are rows. Every number is a value the
 * run reported. Where a row needs a sentence to explain itself, the sentence is
 * derived from those values rather than written in advance.
 */

interface RetrievalObservatoryProps {
  example: MosaicLabMission | undefined;
  /** The most recent live response, or null before the participant has run one. */
  response: SearchResponse | null;
  loading: boolean;
}

function MovementBadge({ movement }: { movement: number }) {
  if (movement === 0) {
    return (
      <span className="labs-matrix-delta held">
        <Minus aria-hidden="true" size={13} /> held
      </span>
    );
  }
  const rose = movement > 0;
  return (
    <span className={`labs-matrix-delta ${rose ? "rose" : "fell"}`}>
      {rose
        ? <ArrowUp aria-hidden="true" size={13} />
        : <ArrowDown aria-hidden="true" size={13} />}
      {Math.abs(movement)}
    </span>
  );
}

function MatrixRowGroup({
  row,
  image,
  focused,
}: {
  row: MatrixRow;
  image: string | undefined;
  focused: ColumnKey | null;
}) {
  return (
    <tbody className={row.isTarget ? "is-target" : undefined}>
      <tr>
        <th scope="row">
          <span className="labs-matrix-rank">{row.finalRank}</span>
          <img alt="" height={44} src={image} width={44} />
          <span className="labs-matrix-identity">
            <strong>{row.product.title}</strong>
            <small>
              {row.product.brand} / {row.product.model}
              {row.isTarget ? <em> · scenario target</em> : null}
            </small>
          </span>
        </th>
        {row.cells.map((cell) => (
          <td
            className={[
              "labs-matrix-cell",
              cell.missing ? "is-missing" : "is-hit",
              focused === cell.key ? "is-focused" : "",
            ].filter(Boolean).join(" ")}
            key={cell.key}
          >
            {cell.missing ? (
              <span className="labs-matrix-miss" title="This stage produced nothing for this row">
                not found
              </span>
            ) : (
              <>
                <strong>{cell.label}</strong>
                {cell.detail ? <small>{cell.detail}</small> : null}
              </>
            )}
          </td>
        ))}
        <td className="labs-matrix-move">
          <span>
            {row.beforeRank} <ArrowDown aria-hidden="true" className="labs-matrix-arrow" size={13} />{" "}
            {row.finalRank}
          </span>
          <MovementBadge movement={row.movement} />
        </td>
      </tr>
      <tr className="labs-matrix-why">
        <td colSpan={7}>
          <p>{row.verdict}</p>
          <ul aria-label={`Why ${row.product.model} matched`}>
            {row.reasons.map((reason) => (
              <li className={reason.kind} key={reason.label}>{reason.label}</li>
            ))}
          </ul>
        </td>
      </tr>
    </tbody>
  );
}

export function RetrievalObservatory({
  example,
  response,
  loading,
}: RetrievalObservatoryProps) {
  const [focused, setFocused] = useState<ColumnKey | null>(null);

  const shown = response ?? seedRunFor(example?.id);
  const isLive = response !== null;

  const matrix = useMemo(
    () => (shown ? buildRetrievalMatrix(shown, example?.target_product_ids ?? []) : null),
    [shown, example],
  );
  const images = useMemo(
    () => productImageMap(matrix?.rows.map((row) => row.product) ?? []),
    [matrix],
  );
  const focusedColumn = matrix?.columns.find((column) => column.key === focused) ?? null;

  return (
    <section className="labs-matrix" aria-labelledby="labs-matrix-title">
      <header className="labs-matrix-heading">
        <div>
          <p className="eyebrow">Five retrievers, one result set</p>
          <h2 id="labs-matrix-title">What each retriever found</h2>
          {matrix ? (
            <p className="labs-matrix-summary">{matrixSummary(matrix)}</p>
          ) : (
            <p className="labs-matrix-summary">
              Run the pipeline to compare this scenario across all five retrievers.
            </p>
          )}
        </div>
        <div className="labs-matrix-provenance">
          {/* Only ever labels a run that is on screen. Printing "Captured run"
              beside an empty matrix would claim provenance for nothing. */}
          {shown ? (
            <>
              <span className={`labs-matrix-badge ${isLive ? "is-live" : "is-captured"}`}>
                {isLive ? "Live run" : "Captured run"}
              </span>
              <dl>
                <div>
                  <dt>Run</dt>
                  <dd className="mono">{shown.search_event_id.slice(0, 8)}</dd>
                </div>
                <div>
                  <dt>{isLive ? "Source" : "Captured"}</dt>
                  <dd>{isLive ? "This browser, just now" : seedProvenance.captured_at}</dd>
                </div>
              </dl>
            </>
          ) : null}
        </div>
      </header>

      {/* The scenario is chosen beside Run pipeline in the masthead, so this only
          reports the query that produced what is below it. */}
      <div className="labs-matrix-controls">
        <span>Query</span>
        <p className="labs-matrix-query">
          <code>{example?.query}</code>
        </p>
      </div>

      {matrix ? (
        <>
          <div className="labs-matrix-scroll">
            <table className="labs-matrix-table">
              <caption className="sr-only">
                Each retriever's rank for every returned product, then the order
                before and after reranking.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Result</th>
                  {matrix.columns.map((column) => (
                    <th key={column.key} scope="col">
                      <button
                        aria-pressed={focused === column.key}
                        className={focused === column.key ? "is-focused" : undefined}
                        onClick={() =>
                          setFocused(focused === column.key ? null : column.key)}
                        type="button"
                      >
                        <strong>{column.label}</strong>
                        <small>{column.mechanism}</small>
                        <span>
                          {column.measure} <em>{column.measureDetail}</em>
                        </span>
                      </button>
                    </th>
                  ))}
                  <th scope="col">
                    <span className="labs-matrix-move-head">
                      <strong>Before / after</strong>
                      <small>position among these rows</small>
                    </span>
                  </th>
                </tr>
              </thead>
              {matrix.rows.map((row) => (
                <MatrixRowGroup
                  focused={focused}
                  image={images.get(row.product.product_id)}
                  key={row.product.product_id}
                  row={row}
                />
              ))}
            </table>
          </div>

          <footer className="labs-matrix-footer">
            {focusedColumn ? (
              <div className="labs-matrix-sql">
                <p className="eyebrow">{focusedColumn.label} in psql</p>
                <CodeBlock code={focusedColumn.sql} label={`${focusedColumn.key}.sql`} />
              </div>
            ) : (
              <p className="labs-matrix-sql-hint">
                Select a column heading to isolate that retriever and read the query
                behind it.
              </p>
            )}
            <p className="labs-matrix-note">
              Arm ranks are positions within each retriever's own candidate list, so
              they run past the twelve rows shown here. <strong>Before / after</strong>
              {" "}compares positions among these rows only: the left number is the
              order that would have shipped with reranking off. Raw arm scores, fused
              scores, and rerank scores are on different scales and are not
              probabilities.
            </p>
          </footer>
        </>
      ) : (
        <p className="labs-matrix-awaiting" role="status">
          {loading
            ? "Embedding the query, running all three arms, fusing, and reranking."
            : `No run for ${example?.discover_label ?? "this scenario"} yet. Run the pipeline to fill the matrix.`}
        </p>
      )}
    </section>
  );
}
