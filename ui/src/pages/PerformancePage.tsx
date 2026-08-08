import { Activity, DatabaseZap, Gauge, HardDrive, Timer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { ErrorState, LoadingState } from "../components/States";
import type { BenchmarkProjection } from "../types";

const benchmarkSql = `BEGIN;
SET LOCAL hnsw.ef_search = 128;
SET LOCAL hnsw.iterative_scan = strict_order;

EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT product_id, embedding <=> :query_embedding AS distance
FROM catalog.product
WHERE domain = :domain
  AND availability = 'In Stock'
ORDER BY embedding <=> :query_embedding
LIMIT 10;
ROLLBACK;`;

export function PerformancePage() {
  const [projection, setProjection] = useState<BenchmarkProjection | null>(null);
  const [error, setError] = useState("");
  const [scale, setScale] = useState(500_000);
  const [efSearch, setEfSearch] = useState(128);
  const [selectivity, setSelectivity] = useState("10");
  const [scan, setScan] = useState("strict_order");

  useEffect(() => {
    api.projection().then(setProjection).catch((cause: Error) => setError(cause.message));
  }, []);

  const row = useMemo(
    () => projection?.rows.find((item) => item.scale === scale),
    [projection, scale],
  );
  const maxLatency = Math.max(...(projection?.rows.map((item) => item.p95_latency_ms) ?? [1]));

  if (error) return <div className="page"><ErrorState message={error} /></div>;
  if (!projection) return <div className="page"><LoadingState label="Loading benchmark envelope" /></div>;

  return (
    <div className="page performance-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Core performance lab</p>
          <h1>HNSW Performance Tuning</h1>
          <p>Compare recall, latency, filter selectivity, and index cost without presenting projections as Aurora measurements.</p>
        </div>
        <span className="projection-badge">Projected package baseline</span>
      </header>

      <div className="performance-layout">
        <aside className="control-panel">
          <h2>Experiment controls</h2>
          <label><span>Catalog scale</span>
            <select value={scale} onChange={(event) => setScale(Number(event.target.value))}>
              {projection.rows.map((item) => <option key={item.scale} value={item.scale}>{item.scale.toLocaleString()}</option>)}
            </select>
          </label>
          <label><span>ef_search <strong>{efSearch}</strong></span>
            <input type="range" min="16" max="512" step="16" value={efSearch} onChange={(event) => setEfSearch(Number(event.target.value))} />
          </label>
          <label><span>Filter selectivity</span>
            <select value={selectivity} onChange={(event) => setSelectivity(event.target.value)}>
              {["100", "25", "10", "1", "0.1"].map((value) => (
                <option key={value} value={value}>{value}%</option>
              ))}
            </select>
          </label>
          <label><span>Iterative scan</span>
            <select value={scan} onChange={(event) => setScan(event.target.value)}>
              <option value="off">Off</option>
              <option value="strict_order">Strict order</option>
              <option value="relaxed_order">Relaxed order</option>
            </select>
          </label>
          <div className="boundary-note">
            <strong>Measurement boundary</strong>
            <p>Changing controls prepares a benchmark configuration. The displayed metrics remain the package projection until the harness records a matching Aurora run.</p>
          </div>
        </aside>

        <section className="performance-main">
          <div className="metric-grid">
            <article><Timer size={20} /><span>Projected p95</span><strong>{row?.p95_latency_ms.toFixed(1)} ms</strong></article>
            <article><Gauge size={20} /><span>Projected recall@10</span><strong>{((row?.recall_at_10 ?? 0) * 100).toFixed(1)}%</strong></article>
            <article><HardDrive size={20} /><span>Projected index</span><strong>{row?.index_size_gb.toLocaleString()} GB</strong></article>
            <article><Activity size={20} /><span>Projected build</span><strong>{row?.build_time_min.toLocaleString()} min</strong></article>
          </div>

          <section className="chart-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">Scale projection</p><h2>p95 latency by catalog size</h2></div>
              <span>1024 dimensions / m=16 / ef_search=128</span>
            </div>
            <div className="bar-chart" role="img" aria-label="Projected p95 latency by catalog size">
              {projection.rows.map((item) => (
                <button key={item.scale} type="button" className={item.scale === scale ? "selected" : ""} onClick={() => setScale(item.scale)}>
                  <span className="bar-value">{item.p95_latency_ms.toFixed(1)} ms</span>
                  <i style={{ height: `${Math.max(12, item.p95_latency_ms / maxLatency * 100)}%` }} />
                  <small>{item.scale >= 1_000_000 ? `${item.scale / 1_000_000}M` : "500K"}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="benchmark-config">
            <div>
              <DatabaseZap size={22} />
              <span><strong>Selected run envelope</strong><small>{scale.toLocaleString()} rows / ef_search={efSearch} / selectivity={selectivity}% / {scan}</small></span>
            </div>
            <CodeBlock code={benchmarkSql.replace("128", String(efSearch)).replace("strict_order", scan)} label="benchmark-query.sql" />
          </section>
        </section>
      </div>
    </div>
  );
}
