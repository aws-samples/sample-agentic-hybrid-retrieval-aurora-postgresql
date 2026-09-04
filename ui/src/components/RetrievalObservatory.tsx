import { ArrowDown, ArrowUp, CircleDashed, Minus } from "lucide-react";
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
import { FINAL_LABEL, FUSED_LABEL } from "../retrievalLanguage";
import type { SearchResponse } from "../types";

/**
 * The Playground's rank table: five stages, one row per result, side by side.
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
  /**
   * Draw for a room rather than for a laptop.
   *
   * Twelve rows, each two table rows deep, do not survive projection: the last
   * of them lands below the fold on every projector this session has been run
   * on. Cutting to the first four alone would routinely hide the row the
   * scenario is about, so the scenario's targets travel with them.
   */
  projector?: boolean;
}

const RANKING_GUIDE = [
  {
    number: "01",
    title: "Find",
    description: "Each retrieval method makes its own candidate list.",
    fields: ["Rank in each arm"],
  },
  {
    number: "02",
    title: "Combine",
    description: "RRF combines positions without comparing unlike raw scores.",
    fields: ["RRF contribution", FUSED_LABEL],
  },
  {
    number: "03",
    title: "Reorder",
    description: "Reranking can only reorder products already in the fused pool.",
    fields: ["Rerank score", FINAL_LABEL],
  },
] as const;

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
  projector = false,
}: RetrievalObservatoryProps) {
  const [focused, setFocused] = useState<ColumnKey | null>(null);

  const matrix = useMemo(
    () => (response ? buildRetrievalMatrix(response, example?.target_product_ids ?? []) : null),
    [response, example],
  );
  const images = useMemo(
    () => productImageMap(matrix?.rows.map((row) => row.product) ?? []),
    [matrix],
  );
  const focusedColumn = matrix?.columns.find((column) => column.key === focused) ?? null;
  const visibleRows = matrix
    ? matrix.rows.filter((row, index) => !projector || index < 4 || row.isTarget)
    : [];

  return (
    <section
      aria-busy={loading}
      className="labs-matrix"
      aria-labelledby="labs-matrix-title"
    >
      {/* h3, not h2: this table lives inside the Rank stage, whose own h2 is
          "Rank". The eyebrow above it read "Five retrievers, one result set" over
          a heading saying the same thing in different words. */}
      <header className="labs-matrix-heading">
        <div>
          <h3 id="labs-matrix-title">
            How each product reached its final position
          </h3>
          {/* No pre-run summary. The dormant block below already names the five
              columns and says what fills them; two sentences asking for the same
              click read as a stalled panel. */}
          {matrix ? (
            <p className="labs-matrix-summary">{matrixSummary(matrix)}</p>
          ) : null}
        </div>
        <div className="labs-matrix-provenance">
          {response ? (
            <>
              <span className="labs-matrix-badge is-live">Live run</span>
              <dl>
                <div>
                  <dt>Run</dt>
                  <dd className="mono">{response.search_event_id.slice(0, 8)}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>This browser, just now</dd>
                </div>
              </dl>
            </>
          ) : null}
        </div>
      </header>

      <ol
        aria-label="How to read the ranking table"
        className="labs-ranking-guide"
      >
        {RANKING_GUIDE.map((step) => (
          <li key={step.title}>
            <span aria-hidden="true" className="labs-ranking-guide-number">
              {step.number}
            </span>
            <div>
              <strong>{step.title}</strong>
              <span>{step.description}</span>
              <ul aria-label={`${step.title} table columns`}>
                {step.fields.map((field) => <li key={field}>{field}</li>)}
              </ul>
            </div>
          </li>
        ))}
      </ol>

      {response ? (
        <div className="labs-matrix-controls">
          <span>Query</span>
          <p className="labs-matrix-query">
            <code>{response.query}</code>
          </p>
        </div>
      ) : null}

      {matrix ? (
        <>
          <div
            aria-label="Retrieval result comparison"
            className="labs-matrix-scroll"
            role="region"
            tabIndex={0}
          >
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
              {visibleRows.map((row) => (
                <MatrixRowGroup
                  focused={focused}
                  image={images.get(row.product.product_id)}
                  key={row.product.product_id}
                  row={row}
                />
              ))}
            </table>
          </div>

          {projector ? (
            // A caption on the table it describes, not an announcement: it says
            // the same thing for as long as projector mode is on, and a live
            // region would have a screen reader read it out on every unrelated
            // update to this table.
            <p className="labs-matrix-projector">
              Projector mode is showing {visibleRows.length} of the{" "}
              {matrix.rows.length} returned rows.
            </p>
          ) : null}

          <footer className="labs-matrix-footer">
            {focusedColumn ? (
              <div className="labs-matrix-sql">
                <p className="labs-matrix-sql-title">
                  <strong>View SQL</strong>
                  {focusedColumn.label} — <code>{focusedColumn.mechanism}</code>
                </p>
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
      ) : loading ? (
        <p className="labs-matrix-awaiting" role="status">
          Embedding the query, running all three arms, fusing, and reranking.
        </p>
      ) : (
        <div className="labs-ranking-empty" role="status">
          <CircleDashed aria-hidden="true" size={18} />
          <div>
            <strong>
              No run for {example?.discover_label ?? "this scenario"} yet.
            </strong>
            <span>
              Run the pipeline to fill the mapped columns above on one result set.
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
