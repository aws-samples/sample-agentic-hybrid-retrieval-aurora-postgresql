import { ArrowRight, Download, LoaderCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { api, ApiError } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { CatalogBuildDrawer } from "../components/CatalogBuildDrawer";
import { HnswSearchGraph } from "../components/HnswSearchGraph";
import { HnswSweep, sweepTakeaway } from "../components/HnswSweep";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { SegmentedControl } from "../components/SegmentedControl";
import { formatBytes, formatMs } from "../hnsw";
import { useSearchParams } from "../navigation";
import { comparableScanModes } from "../scaleBenchmarks";
import type { HnswMeasured, HnswSubstrate } from "../types";
import { PerformancePage } from "./PerformancePage";
import "../inspector.css";
import "../scale-essentials.css";
import "../inspection-editorial.css";

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const amount = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 2 });
/** Plain names first; the column type and bits per number are the detail underneath. */
const formats: Record<string, { title: string; type: string; detail: string }> = {
  fp32: { title: "Full precision", type: "vector", detail: "32 bits per number" },
  halfvec: { title: "Half precision", type: "halfvec", detail: "16 bits per number" },
  binary_two_pass: { title: "Binary, then re-checked", type: "bit", detail: "1 bit per number" },
};
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
  return <p className="scale-measurement-note"><strong>{measured.attribution.attributed ? "Measured on this catalog" : "Earlier catalog benchmark"}</strong> · {new Date(measured.captured_at).toLocaleDateString("en-GB")} · {measured.provenance.queries ?? "Recorded"} queries. {median ? "Typical database time with data already cached (p50)." : "Database time from a sampled query."} Saved measurements do not rerun when the index or settings change.</p>;
}
function Inspect({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <details className={`scale-inspect ${className}`.trim()}><summary>{label}</summary><div>{children}</div></details>;
}
function FilterComparison({ measured }: { measured: HnswMeasured | null }) {
  const [preset, setPreset] = useState("brand");
  const available = measured?.filter_matrix.filter((level) => ["brand", "rating", "domain"].includes(level.preset)) ?? [];
  const level = available.find((item) => item.preset === preset) ?? available[0];
  const rows = comparableScanModes(level);
  const exact = level?.exact_rows_found ?? 0;
  const strictGain = rows.length ? rows[1].rows_returned - rows[0].rows_returned : 0;
  return <ScaleSection id="scale-filters" title="Keep looking after filters." description="A filter can empty the shortlist. Iterative scans keep looking until it fills.">
    {measured && level ? <>
      <div className="scale-selector"><span>Alex’s filter</span><SegmentedControl label="Alex’s filter" options={available.map((item) => ({ value: item.preset, label: item.label }))} value={level.preset} onChange={setPreset} /></div>
      {rows.length ? <>
        <div className="inspector-table-scroll" role="region" aria-label="Off, strict and relaxed scan comparison" tabIndex={0}><table className="inspector-table scale-comparison-table"><thead><tr><th>Scan mode</th><th>Products found · average</th><th>Recall@{measured.provenance.k ?? "k"}</th><th>Server time</th></tr></thead><tbody>{rows.map((row) => <tr key={row.iterative_scan}><th scope="row">{modes[row.iterative_scan].title}<small>{modes[row.iterative_scan].description}</small></th><td><strong>{amount(row.rows_returned)} / {amount(exact)}</strong><span className="scale-found-track" aria-hidden="true"><span style={{ width: `${exact ? Math.min(row.rows_returned / exact, 1) * 100 : 0}%` }} /></span></td><td>{percent(row.recall_at_k)}</td><td>{formatMs(row.server_ms)}</td></tr>)}</tbody></table></div>
        <p className="scale-takeaway">{strictGain > 0 ? `Strict scanning found ${amount(strictGain)} more products on average than Off in this test.` : "Strict scanning did not increase the average number of products in this test."}</p>
        <Inspect label="Measurement details">
          <MeasurementNote measured={measured} />
          <p className="scale-measurement-note">Same filter{rows[0].ef_search != null ? ` · ef_search ${rows[0].ef_search}` : ""} · {rows[0].scan_mem_mb} MB scan memory. Recall is the share of the exact closest matches found.</p>
          <p className="scale-measurement-note">In pgvector 0.8+, <strong>strict and relaxed are both iterative modes.</strong> Relaxed ordering can improve recall. A final sort restores distance order.</p>
        </Inspect>
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
  return <ScaleSection id="scale-representations" title="A smaller index." description="Same embeddings, stored in less space.">
    {measured && representations ? <>
      <div className="inspector-table-scroll" role="region" aria-label="Vector format benchmarks" tabIndex={0}><table className="inspector-table scale-comparison-table"><thead><tr><th>Format</th><th>Index size</th><th>Recall@{representations.k}</th><th>Server time</th></tr></thead><tbody>{rows.map((row) => {
        const format = formats[row.representation] ?? { title: row.representation, type: row.representation, detail: "" };
        return <tr key={row.representation}>
          <th scope="row">{format.title}<small><code>{format.type}</code> · {format.detail}{row.overfetch ? `, ${row.overfetch} re-checked` : ""}</small></th>
          <td>{formatBytes(row.index_size_bytes)}<small>{fullSize && row.index_size_bytes < fullSize ? `${(fullSize / row.index_size_bytes).toFixed(1)}× smaller` : "Baseline"}</small></td>
          <td>{percent(row.recall_at_k)}</td>
          <td>{formatMs(row.server_ms)}</td>
        </tr>;
      })}</tbody></table></div>
      {binaryRows.length ? <div className="scale-selector"><span>Binary: matches re-checked</span><SegmentedControl label="Binary: matches re-checked" options={binaryRows.flatMap((row) => row.overfetch == null ? [] : [{ value: row.overfetch, label: String(row.overfetch) }])} value={selected?.overfetch ?? undefined} onChange={setDepth} /></div> : null}
      <Inspect label="Measurement details">
        <MeasurementNote measured={measured} />
        <p className="scale-measurement-note"><strong>halfvec</strong> stores each number in 16 bits. <strong>Binary storage</strong> keeps one sign bit, then re-checks its shortlist by cosine distance against the original vectors. Re-checking more matches recovers recall, at extra time.</p>
        <p className="scale-measurement-note">{representations.anchors} queries · ef_search {representations.ef_search}. Recall is checked against full-precision exact search. Index size includes graph overhead.</p>
      </Inspect>
    </> : <><div className="scale-format-basics"><span>Full precision · vector</span><span>Half precision · halfvec</span><span>Binary, then re-checked · bit</span></div><p className="inspector-waiting">Format measurements are unavailable for this catalog.</p></>}
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
  return <Inspect label="Benchmarks & SQL">
    <MeasurementNote measured={measured} />
    <h3>Search effort and recall</h3>
    {best ? <p>Best recall in this sweep: <strong>{percent(best.recall_at_k)}</strong> at ef_search {best.ef_search}, in {formatMs(best.server_ms)}. More search effort can reach a point of diminishing returns.</p> : null}
    <div className="inspector-table-scroll" role="region" aria-label="Search effort benchmarks" tabIndex={0}><table className="inspector-table"><thead><tr><th>ef_search</th><th>Recall</th><th>Server time</th><th>Server p95</th></tr></thead><tbody>{measured.ef_sweep.map((row) => <tr key={row.ef_search}><th scope="row">{row.ef_search}</th><td>{percent(row.recall_at_k)}</td><td>{formatMs(row.server_ms)}</td><td>{row.server_p95_ms == null ? "Not recorded" : formatMs(row.server_p95_ms)}</td></tr>)}</tbody></table></div>
    <p className="scale-measurement-note">Exact scan: {formatMs(measured.exact_baseline.server_ms)} database time. Client p50 / p95: {formatMs(measured.exact_baseline.p50_ms)} / {formatMs(measured.exact_baseline.p95_ms)}. These benchmarks cover vector search; embedding, reranking and the Retrieval agent take additional time.</p>
    {deep ? <><h3>Deeper binary search</h3><div className="inspector-table-scroll" role="region" aria-label="Deeper binary benchmarks" tabIndex={0}><table className="inspector-table"><thead><tr><th>Configuration</th><th>Recall@{deep.k}</th><th>Server time</th></tr></thead><tbody>{deep.rows.map((row) => <tr key={row.config}><th scope="row">{row.config}</th><td>{percent(row.recall_at_k)}</td><td>{formatMs(row.server_ms)}</td></tr>)}</tbody></table></div><p>Different search effort, same exact comparison. A smaller index alone does not guarantee a faster query.</p></> : null}
    <h3>Strict and relaxed ordering</h3>
    <CodeBlock label="Iterative scan examples" code={`BEGIN;\nSET LOCAL hnsw.iterative_scan = 'strict_order';\n-- Run the filtered nearest-neighbor query.\nCOMMIT;\n\nBEGIN;\nSET LOCAL hnsw.iterative_scan = 'relaxed_order';\nWITH matches AS MATERIALIZED (\n  SELECT product_id, embedding <=> $1 AS distance\n  FROM mosaic_search.product_listing_view\n  WHERE embedding IS NOT NULL AND category_key = $2\n  ORDER BY distance\n  LIMIT $3\n)\nSELECT * FROM matches ORDER BY distance + 0;\nCOMMIT;`} />
    <p>Strict keeps the returned rows in distance order; it is still approximate search. Relaxed can improve recall, then the outer sort restores order. The <code>+ 0</code> is needed on PostgreSQL 17+.</p>
    <div className="scale-reference-links"><a href="https://github.com/pgvector/pgvector#iterative-index-scans" target="_blank" rel="noreferrer">pgvector scan modes <ArrowRight size={14} /></a><a href="https://aws.amazon.com/blogs/database/scale-pgvector-with-binary-quantization-on-amazon-aurora-postgresql/" target="_blank" rel="noreferrer">AWS guide to smaller vector indexes <ArrowRight size={14} /></a><button type="button" onClick={() => downloadMeasurements(measured)}><Download size={14} />Download measurements</button><Link href="/mosaic-labs/hnsw?view=bench">Full benchmark workbench</Link></div>
  </Inspect>;
}
function ScaleInspector() {
  const [substrate, setSubstrate] = useState<HnswSubstrate | null>(null);
  const [measured, setMeasured] = useState<HnswMeasured | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [pending, setPending] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [illustrationOpen, setIllustrationOpen] = useState(false);
  useEffect(() => {
    let active = true;
    setPending(true); setErrors([]); setUnavailable([]);
    void Promise.allSettled([api.hnswSubstrate(), api.hnswMeasured()]).then(([live, record]) => {
      if (!active) return;
      const failures: string[] = [];
      const conflicts = new Set<string>();
      const rejected = (reason: unknown, fallback: string) => {
        if (reason instanceof ApiError && reason.status === 409) conflicts.add(reason.message);
        else failures.push(fallback);
      };
      if (live.status === "fulfilled") setSubstrate(live.value);
      else { setSubstrate(null); rejected(live.reason, "The current index could not be loaded."); }
      if (record.status === "fulfilled") setMeasured(record.value);
      else { setMeasured(null); rejected(record.reason, "The benchmark results could not be loaded."); }
      setErrors(failures); setUnavailable([...conflicts]); setPending(false);
    });
    return () => { active = false; };
  }, [attempt]);
  const effort = measured?.ef_sweep.length ? measured.ef_sweep : null;
  return <div className="page pipeline-inspector scale-essentials">
    <MosaicLabsTabs active="hnsw" />
    <div className="inspector-intro"><MosaicLabsMasthead title={<>A small shortlist. <span className="inspector-title-emphasis">A much larger search.</span></>} deck="More search effort finds more matches, until it only costs more time." action={<CatalogBuildDrawer />} /></div>
    {substrate ? <ul className="scale-chips" aria-label="Current index"><li>{substrate.corpus.vector_count.toLocaleString()} product embeddings</li><li>{substrate.corpus.dimensions ?? "Unreported"} dimensions</li><li>pgvector {substrate.aurora.vector_extension_version ?? "version not reported"}</li></ul> : null}
    {pending ? <p className="scale-status" role="status"><LoaderCircle className="scale-spinner" size={18} aria-hidden="true" />Reading the catalog and benchmarks…</p> : null}
    {unavailable.length ? <p className="scale-intro-note" role="note">{unavailable.join(" ")}</p> : null}
    {errors.length ? <div className="inspector-error" role="alert">{errors.join(" ")} <button type="button" className="text-button" onClick={() => setAttempt((value) => value + 1)}>Retry loading</button></div> : null}
    {measured && effort ? <section className="scale-hero" aria-labelledby="scale-effort-title"><header><h2 id="scale-effort-title">Recall against speed.</h2><p>{sweepTakeaway(effort)}</p></header><HnswSweep sweep={effort} served={substrate?.retrieval.ef_search ?? null} /><AdvancedBenchmarks measured={measured} /></section> : null}
    <FilterComparison measured={measured} />
    <RepresentationComparison measured={measured} />
    <details className="scale-inspect scale-mechanism" id="scale-mechanism" onToggle={(event) => setIllustrationOpen(event.currentTarget.open)}>
      <summary>How HNSW finds neighbors</summary>
      <div>{illustrationOpen ? <HnswSearchGraph served={substrate ? { efSearch: substrate.retrieval.ef_search, vectors: substrate.corpus.vector_count, dimensions: substrate.corpus.dimensions, definition: substrate.index.definition } : null} /> : null}</div>
    </details>
    <aside className="inspector-scale-link"><div><h2>And when Alex comes back?</h2><p>See what AgentCore remembers about him.</p></div><Link className="scale-next-link" href="/mosaic-labs/memory">Explore session & memory<ArrowRight size={16} aria-hidden="true" /></Link></aside>
  </div>;
}
export function ScaleInspectorPage() {
  const [params] = useSearchParams();
  return params.get("view") === "bench" ? <PerformancePage /> : <ScaleInspector />;
}
