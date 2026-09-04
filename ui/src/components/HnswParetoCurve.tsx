import { CircleAlert, Gauge, Play } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { curvePoints, saturationEf, speedupFactor } from "../hnsw";
import type { HnswEfPoint, HnswMeasured, HnswProbe } from "../types";

const BOX = { width: 520, height: 210 };
const PADDING = { left: 46, right: 22, top: 18, bottom: 34 };
const EASE_IN_OUT = [0.77, 0, 0.175, 1] as const;
const POINT_SPRING = { type: "spring", bounce: 0, duration: 0.35 } as const;
const TOOLTIP = { width: 152, height: 56 };

type HnswParetoCurveProps = {
  measured: HnswMeasured;
  efSearch: number;
  onEfChange: (efSearch: number) => void;
  probe: HnswProbe | null;
  probeError: string;
  probing: boolean;
  onProbe: () => void;
};

function pointFor(sweep: HnswEfPoint[], efSearch: number) {
  return sweep.find((point) => point.ef_search === efSearch) ?? sweep[0];
}

/**
 * The measured recall/latency curve, and a button that re-runs it for real.
 *
 * Replaces a decorative four-row dot animation that captioned itself as not being a
 * captured plan. Dragging the slider moves along the measured points with no network
 * call; "Run on Aurora now" issues the real query and renders the live result beside
 * the measured one, labelled differently. The two agreeing is the credibility; the two
 * disagreeing is also information, so it is shown rather than hidden.
 */
export function HnswParetoCurve({
  measured,
  efSearch,
  onEfChange,
  probe,
  probeError,
  probing,
  onProbe,
}: HnswParetoCurveProps) {
  const sweep = measured.ef_sweep;
  const points = curvePoints(sweep, BOX);
  const saturation = saturationEf(sweep);
  const selected = pointFor(sweep, efSearch);
  const selectedIndex = sweep.findIndex((point) => point.ef_search === efSearch);
  const selectedPoint = points[selectedIndex < 0 ? 0 : selectedIndex];
  const exact = measured.exact_baseline;
  const speedup = speedupFactor(exact.p50_ms, selected.server_ms);
  const reduceMotion = useReducedMotion() ?? false;
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const hoveredPoint = hoveredIndex === null ? null : points[hoveredIndex];
  const hoveredMeasurement = hoveredIndex === null ? null : sweep[hoveredIndex];
  const tooltipPosition = hoveredPoint
    ? {
        x: Math.min(
          Math.max(hoveredPoint.x - TOOLTIP.width / 2, 4),
          BOX.width - TOOLTIP.width - 4,
        ),
        y:
          hoveredPoint.y > TOOLTIP.height + 18
            ? hoveredPoint.y - TOOLTIP.height - 12
            : hoveredPoint.y + 12,
      }
    : null;

  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");

  return (
    <section className="hnsw-pareto" aria-labelledby="hnsw-pareto-title">
      <header>
        <div>
          <h2 id="hnsw-pareto-title">Recall you can buy, and where buying stops.</h2>
          <p>
            Every point below was measured on {measured.provenance.queries ?? 0} test
            searches against the exact answers. Dragging the control moves along those
            measurements. It does not recompute them.
          </p>
        </div>
        <span className="hnsw-evidence-badge measured">MEASURED</span>
      </header>

      <div className="hnsw-pareto-layout">
        <figure className="hnsw-pareto-plot">
          <svg
            aria-label={
              saturation === null
                ? "Recall against server time, no measurements available"
                : `Recall against server time across ${sweep.length} measured ef_search values. ` +
                  `Recall stops improving at ef_search ${saturation}.`
            }
            role="group"
            viewBox={`0 0 ${BOX.width + PADDING.left + PADDING.right} ${
              BOX.height + PADDING.top + PADDING.bottom
            }`}
          >
            <g transform={`translate(${PADDING.left} ${PADDING.top})`}>
              <line className="axis" x1="0" y1={BOX.height} x2={BOX.width} y2={BOX.height} />
              <line className="axis" x1="0" y1="0" x2="0" y2={BOX.height} />
              {saturation !== null ? (
                <line
                  className="saturation"
                  x1={points[sweep.findIndex((p) => p.ef_search === saturation)]?.x ?? 0}
                  y1="0"
                  x2={points[sweep.findIndex((p) => p.ef_search === saturation)]?.x ?? 0}
                  y2={BOX.height}
                />
              ) : null}
              <path className="curve" d={path} />
              {points.map((point, index) => (
                <g
                  aria-label={
                    `ef_search ${point.ef}: ${sweep[index].server_ms} ms, ` +
                    `${(sweep[index].recall_at_k * 100).toFixed(1)}% recall, ` +
                    `${sweep[index].shared_hit_blocks.toLocaleString()} buffers`
                  }
                  className="pareto-point-target"
                  key={point.ef}
                  onBlur={() => setHoveredIndex(null)}
                  onFocus={() => setHoveredIndex(index)}
                  onPointerEnter={() => setHoveredIndex(index)}
                  onPointerLeave={() => setHoveredIndex(null)}
                  role="img"
                  tabIndex={0}
                >
                  <circle
                    aria-hidden="true"
                    className="point-hit"
                    cx={point.x}
                    cy={point.y}
                    r={Math.max(point.radius + 8, 13)}
                  />
                  <circle
                    className={
                      reduceMotion && point.ef === efSearch ? "point active" : "point"
                    }
                    cx={point.x}
                    cy={point.y}
                    r={point.radius}
                  />
                  <text className="point-label" x={point.x} y={BOX.height + 18}>
                    {point.ef}
                  </text>
                  <title>
                    ef_search {point.ef}: {sweep[index].server_ms} ms,{" "}
                    {sweep[index].shared_hit_blocks.toLocaleString()} buffers, recall{" "}
                    {(sweep[index].recall_at_k * 100).toFixed(1)}%
                  </title>
                </g>
              ))}
              {!reduceMotion && selectedPoint ? (
                <motion.circle
                  animate={{
                    transform: `translate(${selectedPoint.x}px, ${selectedPoint.y}px)`,
                  }}
                  className="point active point-selection"
                  initial={false}
                  r={selectedPoint.radius}
                  transition={POINT_SPRING}
                />
              ) : null}
              <AnimatePresence>
                {hoveredPoint && hoveredMeasurement && tooltipPosition ? (
                  <motion.g
                    animate={{
                      opacity: 1,
                      transform: `translate(${tooltipPosition.x}px, ${tooltipPosition.y}px)`,
                    }}
                    aria-hidden="true"
                    className="pareto-point-tooltip"
                    exit={{ opacity: 0 }}
                    initial={{
                      opacity: 0,
                      transform: `translate(${tooltipPosition.x}px, ${
                        tooltipPosition.y + (reduceMotion ? 0 : 4)
                      }px)`,
                    }}
                    key={hoveredPoint.ef}
                    transition={{ duration: 0.16, ease: EASE_IN_OUT }}
                  >
                    <rect height={TOOLTIP.height} rx="7" width={TOOLTIP.width} />
                    <text>
                      <tspan className="tooltip-title" x="10" y="16">
                        ef_search {hoveredPoint.ef}
                      </tspan>
                      <tspan x="10" y="32">
                        {hoveredMeasurement.server_ms} ms ·{" "}
                        {(hoveredMeasurement.recall_at_k * 100).toFixed(1)}% recall
                      </tspan>
                      <tspan x="10" y="47">
                        {hoveredMeasurement.shared_hit_blocks.toLocaleString()} buffers
                      </tspan>
                    </text>
                  </motion.g>
                ) : null}
              </AnimatePresence>
            </g>
            <text
              className="axis-title axis-title-x"
              x={PADDING.left + BOX.width / 2}
              y={BOX.height + PADDING.top + 30}
            >
              ef_search, positioned by measured server time (log)
            </text>
            <text
              className="axis-title"
              transform={`translate(12 ${PADDING.top + BOX.height / 2}) rotate(-90)`}
            >
              Recall@10
            </text>
          </svg>
          <figcaption>
            Point size is buffer count: {sweep[0]?.shared_hit_blocks.toLocaleString()} to{" "}
            {sweep.at(-1)?.shared_hit_blocks.toLocaleString()} shared hits. The vertical
            rule marks where recall stops improving.
          </figcaption>
        </figure>

        <div className="hnsw-pareto-readout">
          <label className="hnsw-pareto-control">
            <span>
              <code>hnsw.ef_search</code>
              <output>{efSearch}</output>
            </span>
            <input
              aria-label="hnsw.ef_search"
              max={sweep.length - 1}
              min={0}
              onChange={(event) => onEfChange(sweep[Number(event.target.value)].ef_search)}
              step={1}
              type="range"
              value={selectedIndex < 0 ? 0 : selectedIndex}
            />
            <small>
              Steps through the measured values only. Interpolating between them would
              invent numbers.
            </small>
          </label>

          <dl className="hnsw-pareto-metrics">
            <div>
              <dt>Server time</dt>
              <dd>{selected.server_ms} ms</dd>
            </div>
            <div>
              <dt>Recall@10</dt>
              <dd>{(selected.recall_at_k * 100).toFixed(1)}%</dd>
            </div>
            <div>
              <dt>Buffers touched</dt>
              <dd>{selected.shared_hit_blocks.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Versus exact</dt>
              <dd>{speedup}x faster</dd>
            </div>
          </dl>

          <p className="hnsw-pareto-exact">
            <Gauge aria-hidden="true" size={15} />
            <span>
              The exact answer costs <strong>{exact.p50_ms} ms</strong> and{" "}
              {exact.shared_hit_blocks.toLocaleString()} buffers, a {exact.node} over every
              row, with <code>{exact.method}</code>.
            </span>
          </p>

          {saturation !== null ? (
            <p className="hnsw-pareto-saturation">
              <span>
              Recall stops improving at <strong>ef_search {saturation}</strong>. Past it,
              ef_search {sweep.at(-1)?.ef_search} spends{" "}
              {(
                (sweep.at(-1)!.shared_hit_blocks /
                  pointFor(sweep, saturation).shared_hit_blocks)
              ).toFixed(1)}
              x the buffers for the same {(pointFor(sweep, saturation).recall_at_k * 100).toFixed(1)}
              %.
              </span>
            </p>
          ) : null}

          <button
            className="hnsw-probe-button"
            disabled={probing}
            onClick={onProbe}
            type="button"
          >
            <Play aria-hidden="true" size={14} />
            {probing ? "Running on Aurora..." : "Run on Aurora now"}
          </button>

          {probeError ? (
            <p className="hnsw-probe-error" role="alert">
              <CircleAlert aria-hidden="true" size={15} />
              {probeError}
            </p>
          ) : null}

          {probe ? (
            <div className="hnsw-probe-result">
              <header>
                <span className="hnsw-evidence-badge live probe">LIVE PROBE</span>
                <code>
                  {probe.plan.node}
                  {probe.plan.index_name ? ` using ${probe.plan.index_name}` : ""}
                </code>
              </header>
              <dl>
                <div>
                  <dt>Server time</dt>
                  <dd>{probe.plan.server_ms} ms</dd>
                </div>
                <div>
                  <dt>Recall@{probe.settings.k}</dt>
                  <dd>{(probe.recall_at_k * 100).toFixed(1)}%</dd>
                </div>
                <div>
                  <dt>Buffers</dt>
                  <dd>{probe.plan.shared_hit_blocks.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Rows</dt>
                  <dd>
                    {probe.rows_returned} of {probe.exact_rows_available}
                  </dd>
                </div>
              </dl>
              <footer>
                Planner estimated {probe.plan.estimated_rows.toLocaleString()} rows at cost{" "}
                {probe.plan.estimated_total_cost.toLocaleString()}. HNSW has no selectivity
                estimate; the <code>LIMIT</code> is what makes the plan cheap.
              </footer>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
