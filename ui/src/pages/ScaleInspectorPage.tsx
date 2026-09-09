import { ArrowRight, ChevronDown, Download } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { HnswSearchGraph } from "../components/HnswSearchGraph";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { formatBytes } from "../hnsw";
import { useSearchParams } from "../navigation";
import { comparableScanModes } from "../scaleBenchmarks";
import type { HnswMeasured, HnswSubstrate } from "../types";
import { PerformancePage } from "./PerformancePage";
import "../inspector.css";
import "../scale-essentials.css";

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const amount = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 2 });
const modes = {
  off: { title: "Off", description: "Stop after the first pass." },
  strict_order: { title: "Strict", description: "Keep scanning, in distance order." },
  relaxed_order: { title: "Relaxed", description: "Keep scanning, allow small order changes." },
};
function ScaleSection({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }) {
  return <section className="scale-essential-section" id={id} aria-labelledby={`${id}-title`}><header><h2 id={`${id}-title`}>{title}</h2><p>{description}</p></header><div>{children}</div></section>;
}
function MeasurementNote({ measured }: { measured: HnswMeasured }) {
  const median = measured.ef_sweep.some((point) => point.server_p95_ms != null);
  return <p className="scale-measurement-note"><strong>{measured.attribution.attributed ? "Measured on this catalog" : "Earlier catalog benchmark"}</strong> · {new Date(measured.captured_at).toLocaleDateString("en-GB")} · {measured.provenance.queries ?? "Recorded"} queries. {median ? "Warm database time, p50." : "Database time from a sampled query."}</p>;
}
function FilterComparison({ measured }: { measured: HnswMeasured | null }) {
  const [preset, setPreset] = useState("brand_stock");
  const available = measured?.filter_matrix.filter((level) => ["brand_stock", "rating", "domain"].includes(level.preset)) ?? [];
  const level = available.find((item) => item.preset === preset) ?? available[0];
  const rows = comparableScanModes(level);
  const exact = level?.exact_rows_found ?? 0;
  const strictGain = rows.length ? rows[1].rows_returned - rows[0].rows_returned : 0;
  return <ScaleSection id="scale-filters" title="Keep looking after filters." description="Alex wants products that fit his preferences. Filters can remove nearby matches; iterative scans look for more.">
    <p className="scale-intro-note">In pgvector 0.8+, <strong>strict and relaxed are both iterative modes.</strong> Relaxed ordering can improve recall. A final sort restores distance order.</p>
    {measured && level ? <>
      <div className="scale-selector"><label htmlFor="scale-filter">Alex’s filter</label><select id="scale-filter" value={level.preset} onChange={(event) => setPreset(event.target.value)}>{available.map((item) => <option key={item.preset} value={item.preset}>{item.label}</option>)}</select></div>
      <MeasurementNote measured={measured} />
      {rows.length ? <>
        <div className="inspector-table-scroll" role="region" aria-label="Off, strict and relaxed scan comparison" tabIndex={0}><table className="inspector-table scale-comparison-table"><thead><tr><th>Scan mode</th><th>Products found · average</th><th>Recall@{measured.provenance.k ?? "k"}</th><th>Server time</th></tr></thead><tbody>{rows.map((row) => <tr key={row.iterative_scan}><th scope="row">{modes[row.iterative_scan].title}<small>{modes[row.iterative_scan].description}</small></th><td><strong>{amount(row.rows_returned)} / {amount(exact)}</strong><span className="scale-found-track" aria-hidden="true"><span style={{ width: `${exact ? Math.min(row.rows_returned / exact, 1) * 100 : 0}%` }} /></span></td><td>{percent(row.recall_at_k)}</td><td>{row.server_ms} ms</td></tr>)}</tbody></table></div>
        <p className="scale-takeaway">{strictGain > 0 ? `Strict scanning found ${amount(strictGain)} more products on average than Off in this test.` : "More scanning did not increase the average number of products in this test."} Scans still stop at their work limit.</p>
        <p className="scale-measurement-note">Same filter{rows[0].ef_search != null ? ` · ef_search ${rows[0].ef_search}` : ""} · {rows[0].scan_mem_mb} MB scan memory. Recall is the share of the exact closest matches found.</p>
      </> : <p>No comparison with matching search and memory settings is available.</p>}
    </> : <p className="inspector-waiting">Filter measurements are not available yet.</p>}
  </ScaleSection>;
}
function RepresentationComparison({ measured }: { measured: HnswMeasured | null }) {
  const [depth, setDepth] = useState<number | null>(null);
  const representations = measured?.representations;
  const binaryRows = representations?.rows.filter((row) => row.representation === "binary_two_pass").sort((a, b) => (a.overfetch ?? 0) - (b.overfetch ?? 0)) ?? [];
  const selected = binaryRows.find((row) => row.overfetch === depth) ?? binaryRows.at(-1);
  const rows = [...representations?.rows.filter((row) => ["fp32", "halfvec"].includes(row.representation)) ?? [], ...selected ? [selected] : []];
  const fullSize = rows.find((row) => row.representation === "fp32")?.index_size_bytes;
  return <ScaleSection id="scale-representations" title="A smaller index." description="Keep the same embeddings. Change how the index stores them, then compare size, speed and matches.">
    <p className="scale-intro-note"><strong>halfvec</strong> stores each number in 16 bits. <strong>Binary quantization</strong> keeps one sign bit, then checks its shortlist against the original vectors.</p>
    {measured && representations ? <>
      <MeasurementNote measured={measured} />
      <div className="inspector-table-scroll" role="region" aria-label="Vector format benchmarks" tabIndex={0}><table className="inspector-table scale-comparison-table"><thead><tr><th>Format</th><th>Index size</th><th>Recall@{representations.k}</th><th>Server time</th></tr></thead><tbody>{rows.map((row) => <tr key={row.representation}><th scope="row">{row.representation === "fp32" ? "vector · full precision" : row.representation === "halfvec" ? "halfvec" : "Binary + cosine"}{row.overfetch ? <small>{row.overfetch} candidates checked</small> : null}</th><td>{formatBytes(row.index_size_bytes)}{fullSize && row.index_size_bytes < fullSize ? <small>{(fullSize / row.index_size_bytes).toFixed(1)}× smaller</small> : null}</td><td>{percent(row.recall_at_k)}</td><td>{row.server_ms} ms</td></tr>)}</tbody></table></div>
      {binaryRows.length ? <div className="scale-selector"><label htmlFor="binary-depth">Binary candidates to check</label><select id="binary-depth" value={selected?.overfetch ?? ""} onChange={(event) => setDepth(Number(event.target.value))}>{binaryRows.map((row) => <option key={row.overfetch} value={row.overfetch ?? ""}>{row.overfetch}</option>)}</select><span>Checking more candidates can recover matches, at extra cost.</span></div> : null}
      <p className="scale-measurement-note">{representations.anchors} queries · ef_search {representations.ef_search}. Recall is checked against full-precision exact search. Index size includes graph overhead.</p>
    </> : <><div className="scale-format-basics"><span>vector · full precision</span><span>halfvec · smaller numbers</span><span>Binary · sign bits + cosine check</span></div><p className="inspector-waiting">Format measurements are unavailable for this catalog.</p></>}
  </ScaleSection>;
}
function downloadMeasurements(measured: HnswMeasured) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(measured, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "mosaic-hnsw-measurements.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function AdvancedBenchmarks({ measured }: { measured: HnswMeasured }) {
  const best = [...measured.ef_sweep].sort((a, b) => b.recall_at_k - a.recall_at_k || a.server_ms - b.server_ms)[0];
  const deep = measured.representations?.blog_operating_point;
  return <details className="scale-advanced"><summary>Benchmarks & SQL <span>For a closer look</span><ChevronDown size={20} aria-hidden="true" /></summary><div>
    <MeasurementNote measured={measured} />
    <h3>Search effort and recall</h3>
    {best ? <p>Best recall in this sweep: <strong>{percent(best.recall_at_k)}</strong> at ef_search {best.ef_search}, in {best.server_ms} ms. More search effort can reach a point of diminishing returns.</p> : null}
    <div className="inspector-table-scroll" role="region" aria-label="Search effort benchmarks" tabIndex={0}><table className="inspector-table"><thead><tr><th>ef_search</th><th>Recall</th><th>Server time</th><th>Server p95</th></tr></thead><tbody>{measured.ef_sweep.map((row) => <tr key={row.ef_search}><th scope="row">{row.ef_search}</th><td>{percent(row.recall_at_k)}</td><td>{row.server_ms} ms</td><td>{row.server_p95_ms == null ? "Not recorded" : `${row.server_p95_ms} ms`}</td></tr>)}</tbody></table></div>
    <p className="scale-measurement-note">Exact scan: {measured.exact_baseline.server_ms} ms database time. Client p50 / p95: {measured.exact_baseline.p50_ms} / {measured.exact_baseline.p95_ms} ms. These benchmarks cover vector search; embedding, reranking and the agent take additional time.</p>
    {deep ? <><h3>Deeper binary search</h3><div className="inspector-table-scroll" role="region" aria-label="Deeper binary benchmarks" tabIndex={0}><table className="inspector-table"><thead><tr><th>Configuration</th><th>Recall@{deep.k}</th><th>Server time</th></tr></thead><tbody>{deep.rows.map((row) => <tr key={row.config}><th scope="row">{row.config}</th><td>{percent(row.recall_at_k)}</td><td>{row.server_ms} ms</td></tr>)}</tbody></table></div><p>Different search effort, same exact comparison. A smaller index alone does not guarantee a faster query.</p></> : null}
    <h3>Strict and relaxed ordering</h3>
    <CodeBlock label="Iterative scan examples" code={`BEGIN;\nSET LOCAL hnsw.iterative_scan = 'strict_order';\n-- Run the filtered nearest-neighbor query.\nCOMMIT;\n\nBEGIN;\nSET LOCAL hnsw.iterative_scan = 'relaxed_order';\nWITH matches AS MATERIALIZED (\n  SELECT product_id, embedding <=> $1 AS distance\n  FROM mosaic_search.product_document\n  WHERE embedding IS NOT NULL AND category_key = $2\n  ORDER BY distance\n  LIMIT $3\n)\nSELECT * FROM matches ORDER BY distance + 0;\nCOMMIT;`} />
    <p>Strict keeps the returned rows in distance order; it is still approximate search. Relaxed can improve recall, then the outer sort restores order. The <code>+ 0</code> is needed on PostgreSQL 17+.</p>
    <div className="scale-reference-links"><a href="https://github.com/pgvector/pgvector#iterative-index-scans" target="_blank" rel="noreferrer">pgvector scan modes <ArrowRight size={14} /></a><a href="https://aws.amazon.com/blogs/database/scale-pgvector-with-binary-quantization-on-amazon-aurora-postgresql/" target="_blank" rel="noreferrer">AWS binary quantization study <ArrowRight size={14} /></a><button type="button" onClick={() => downloadMeasurements(measured)}><Download size={14} />Download measurements</button><Link href="/mosaic-labs/hnsw?view=bench">Full benchmark workbench <ArrowRight size={14} /></Link></div>
  </div></details>;
}
function ScaleInspector() {
  const [substrate, setSubstrate] = useState<HnswSubstrate | null>(null);
  const [measured, setMeasured] = useState<HnswMeasured | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setPending(true); setErrors([]);
    void Promise.allSettled([api.hnswSubstrate(), api.hnswMeasured()]).then(([live, record]) => {
      if (!active) return;
      const failures: string[] = [];
      if (live.status === "fulfilled") setSubstrate(live.value);
      else { setSubstrate(null); failures.push("The current index could not be loaded."); }
      if (record.status === "fulfilled") setMeasured(record.value);
      else { setMeasured(null); failures.push("The benchmark results could not be loaded."); }
      setErrors(failures); setPending(false);
    });
    return () => { active = false; };
  }, [attempt]);
  return <div className="page pipeline-inspector scale-essentials">
    <MosaicLabsTabs active="hnsw" />
    <div className="inspector-intro"><MosaicLabsMasthead title={<>A small shortlist.<br />A much larger search.</>} deck="How Mosaic finds a fit for Alex across the workspace catalog." /></div>
    {substrate ? <p className="scale-catalog-context">{substrate.corpus.vector_count.toLocaleString()} product embeddings · {substrate.corpus.dimensions} dimensions · pgvector {substrate.aurora.vector_extension_version}</p> : null}
    {pending ? <p role="status">Reading the catalog and benchmarks…</p> : null}
    {errors.length ? <div className="inspector-error" role="alert">{errors.join(" ")} <button type="button" className="text-button" onClick={() => setAttempt((value) => value + 1)}>Retry loading</button></div> : null}
    <ScaleSection id="scale-mechanism" title="How it finds neighbors" description="Follow Alex’s search through an HNSW graph—layers of connected products."><HnswSearchGraph /></ScaleSection>
    <FilterComparison measured={measured} />
    <RepresentationComparison measured={measured} />
    {measured ? <AdvancedBenchmarks measured={measured} /> : null}
    <aside className="inspector-scale-link"><div><h2>And when Alex comes back?</h2><p>See how AgentCore keeps conversation details and recalls what matters for the next request.</p></div><Link href="/mosaic-labs/memory">Explore session & memory <ArrowRight size={18} aria-hidden="true" /></Link></aside>
  </div>;
}
export function ScaleInspectorPage() {
  const [params] = useSearchParams();
  return params.get("view") === "bench" ? <PerformancePage /> : <ScaleInspector />;
}
