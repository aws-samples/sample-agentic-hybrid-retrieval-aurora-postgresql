import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { HnswFilterLevel, HnswFilterMode } from "../types";

type ScanMode = HnswFilterMode["iterative_scan"];

const SCAN_MODES: Array<[ScanMode, string]> = [
  ["off", "Off"],
  ["strict_order", "Strict"],
  ["relaxed_order", "Relaxed"],
];

/**
 * What each preset demonstrates, keyed by the `character` the measurement recorded.
 *
 * The captions are deliberately about *why*, because the numbers alone read as noise:
 * a 26% filter failing worse than a 17% one looks like a mistake until the neighbourhood
 * correlation is named.
 */
const CHARACTER_NOTES: Record<string, { headline: string; detail: string }> = {
  unfiltered: {
    headline: "No filter, no problem.",
    detail:
      "The baseline. Every later row should be read against this one rather than against an intuition.",
  },
  uncorrelated: {
    headline: "Selective, and uncorrelated with the neighbourhood.",
    detail:
      "A rating floor cuts most of the corpus but is spread evenly through vector space, so the candidates HNSW visits still contain matches. Iterative scan is not needed.",
  },
  anti_correlated: {
    headline: "Less selective, and far worse.",
    detail:
      "This filter is more permissive than the rating floor and performs dramatically worse, because it is anti-correlated with where the query lives: measured, 100 of the 100 nearest neighbours of a consumer-electronics anchor are also consumer electronics. Selectivity is the metric everyone reaches for and it predicts the wrong answer here. Correlation is the risk.",
  },
  selective_uncorrelated: {
    headline: "Narrow enough that the graph runs out of matches.",
    detail:
      "Under a thousand rows qualify. Turning iterative scan on recovers most of them, at roughly six times the buffers.",
  },
  selective_correlated: {
    headline: "The knob whose name suggests it should help, and does not.",
    detail:
      "Raising max_scan_tuples from 20,000 to 1,000,000 changes nothing here: measured zero rows at 20K, 100K, 500K and 1M alike. The binding limit is work_mem x scan_mem_multiplier. Raise the budget and rows appear; raise the tuple cap and nothing does.",
  },
  planner_abandons_hnsw: {
    headline: "Postgres stops using the index, correctly.",
    detail:
      "At six matching rows the planner abandons HNSW for a filtered exact scan and returns every one of them. HNSW is not always the answer, and the planner already knows that.",
  },
};

type HnswFilterMatrixProps = {
  levels: HnswFilterLevel[];
  preset: string;
  scan: ScanMode;
  scanMemMb: number;
  workMemMb: number;
  onPresetChange: (preset: string) => void;
  onScanChange: (scan: ScanMode) => void;
  onScanMemChange: (scanMemMb: number) => void;
};

function findMode(
  level: HnswFilterLevel | undefined,
  scan: ScanMode,
  scanMemMb: number,
): HnswFilterMode | undefined {
  if (!level) return undefined;
  return (
    level.modes.find(
      (mode) => mode.iterative_scan === scan && mode.scan_mem_mb === scanMemMb,
    ) ?? level.modes.find((mode) => mode.iterative_scan === scan)
  );
}

/**
 * The filtered-retrieval cliff, as a matrix a participant can walk.
 *
 * Post-filter HNSW has three distinct failure modes with three different fixes, and the
 * only way to tell them apart is to see rows-returned against rows-that-exist. Each
 * state here is a measured cell, not a model.
 */
export function HnswFilterMatrix({
  levels,
  preset,
  scan,
  scanMemMb,
  workMemMb,
  onPresetChange,
  onScanChange,
  onScanMemChange,
}: HnswFilterMatrixProps) {
  const level = levels.find((candidate) => candidate.preset === preset) ?? levels[0];
  const mode = findMode(level, scan, scanMemMb);
  const budgets = [...new Set(level?.modes.map((entry) => entry.scan_mem_mb))].sort(
    (left, right) => left - right,
  );
  const note = level ? CHARACTER_NOTES[level.character] : undefined;
  const shortfall = mode ? level.exact_rows_found - mode.rows_returned : 0;
  const emptyForSome = mode ? mode.min_rows_returned === 0 : false;

  return (
    <section className="hnsw-cliff" aria-labelledby="hnsw-cliff-title">
      <header>
        <div>
          <h2 id="hnsw-cliff-title">Add a WHERE clause and the guarantees change.</h2>
          <p>
            Rows returned against rows that exist, measured for every combination below.
            Selectivity is on each button; it is not what predicts the outcome.
          </p>
        </div>
        <span className="hnsw-evidence-badge measured">MEASURED</span>
      </header>

      <div className="hnsw-cliff-controls">
        <div className="hnsw-cliff-presets" role="group" aria-label="Filter preset">
          {levels.map((candidate) => (
            <button
              aria-pressed={candidate.preset === preset}
              className={candidate.preset === preset ? "active" : ""}
              key={candidate.preset}
              onClick={() => onPresetChange(candidate.preset)}
              type="button"
            >
              <strong>{candidate.label}</strong>
              <small>
                {candidate.matching_rows.toLocaleString()} rows ·{" "}
                {(candidate.selectivity * 100).toFixed(candidate.selectivity < 0.01 ? 3 : 1)}%
                selective
              </small>
            </button>
          ))}
        </div>

        <div className="hnsw-cliff-knobs">
          <fieldset>
            <legend>
              <code>hnsw.iterative_scan</code>
            </legend>
            <div>
              {SCAN_MODES.map(([value, label]) => (
                <label key={value}>
                  <input
                    checked={scan === value}
                    name="hnsw-iterative-scan"
                    onChange={() => onScanChange(value)}
                    type="radio"
                    value={value}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>
              Memory budget <code>work_mem x scan_mem_multiplier</code>
            </legend>
            <div>
              {budgets.map((budget) => (
                <label key={budget}>
                  <input
                    checked={scanMemMb === budget}
                    name="hnsw-scan-mem"
                    onChange={() => onScanMemChange(budget)}
                    type="radio"
                    value={budget}
                  />
                  <span>
                    {budget} MB
                    <small>
                      x{Math.round((budget / workMemMb) * 10) / 10}
                      {budget === workMemMb ? " (pre-fix)" : " (shipped)"}
                    </small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </div>

      {mode && level ? (
        <div className="hnsw-cliff-readout" aria-live="polite">
          <div className={shortfall > 0 ? "hnsw-cliff-rows short" : "hnsw-cliff-rows"}>
            {shortfall > 0 ? (
              <CircleAlert aria-hidden="true" size={20} />
            ) : (
              <CircleCheck aria-hidden="true" size={20} />
            )}
            <strong>
              {mode.rows_returned} of {level.exact_rows_found} rows
            </strong>
            <span>
              {shortfall > 0
                ? `${shortfall.toFixed(2)} missing on average`
                : "complete result set"}
            </span>
            {emptyForSome ? (
              <em>at least one anchor returned nothing at all</em>
            ) : null}
          </div>

          <dl className="hnsw-cliff-metrics">
            <div>
              <dt>Recall@10</dt>
              <dd>{(mode.recall_at_k * 100).toFixed(1)}%</dd>
            </div>
            <div>
              <dt>Server time</dt>
              <dd>{mode.server_ms} ms</dd>
            </div>
            <div>
              <dt>Buffers touched</dt>
              <dd>{mode.shared_hit_blocks.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Plan node</dt>
              <dd>{mode.node}</dd>
            </div>
          </dl>

          {note ? (
            <div className="hnsw-cliff-note">
              <Info aria-hidden="true" size={16} />
              <div>
                <strong>{note.headline}</strong>
                <p>{note.detail}</p>
              </div>
            </div>
          ) : null}

          <details className="hnsw-cliff-sql">
            <summary>The query and the settings behind this cell</summary>
            <pre>
              <code>
                {`SET hnsw.ef_search = 100;
SET hnsw.iterative_scan = '${mode.iterative_scan}';
SET hnsw.scan_mem_multiplier = ${mode.scan_mem_multiplier};

SELECT product_id
FROM mosaic_search.product_document
WHERE embedding IS NOT NULL${level.predicate_sql ? `\n  AND ${level.predicate_sql}` : ""}
ORDER BY embedding <=> $1
LIMIT 10;`}
              </code>
            </pre>
          </details>
        </div>
      ) : null}
    </section>
  );
}
