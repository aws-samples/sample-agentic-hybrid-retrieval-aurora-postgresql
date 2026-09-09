import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { HnswFilterLevel, HnswFilterMode } from "../types";
import { HnswMeasuredBadge } from "./HnswMeasuredBadge";

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
      "A rating floor can leave matches near many query vectors. Compare Off with Strict and Relaxed to see whether another pass recovers more of them.",
  },
  anti_correlated: {
    headline: "Less selective, and far worse.",
    detail:
      "A home-office filter can remove the nearby products for queries from other domains. How close the matching products are matters as well as how many products pass the filter.",
  },
  selective_uncorrelated: {
    headline: "Narrow enough that the graph runs out of matches.",
    detail:
      "A brand and stock filter leaves a small part of the catalog. Iterative scans can recover more matches, with extra work. Compare the returned rows, recall and time together.",
  },
  selective_correlated: {
    headline: "More scanning still has a work limit.",
    detail:
      "A narrow filter can need more scanning than the available memory and tuple budget allow. The measured memory settings show whether extra room helped this query set.",
  },
  planner_abandons_hnsw: {
    headline: "Postgres stops using the index, correctly.",
    detail:
      "For a very small matching set, PostgreSQL can choose a filtered exact scan. The plan node shows which path this measurement used.",
  },
};

type HnswFilterMatrixProps = {
  levels: HnswFilterLevel[];
  /** Whether the artifact these numbers live in describes the connected cluster. */
  attributed: boolean;
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
  attributed,
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
        <HnswMeasuredBadge attributed={attributed} />
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
