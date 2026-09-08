import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { formatBytes } from "../hnsw";
import { useSearchParams } from "../navigation";
import type { HnswMeasured, HnswSubstrate } from "../types";
import { PerformancePage } from "./PerformancePage";
import { InspectorDetail, InspectorSection } from "./PlaygroundPage";
import "../inspector.css";

function RecallPlot({ measured }: { measured: HnswMeasured }) {
  const points = measured.ef_sweep;
  if (!points.length) return <p>No recall sweep was recorded.</p>;
  const maxTime = Math.max(...points.map((point) => point.server_ms), 1);
  const x = (time: number) => 56 + time / maxTime * 560;
  const y = (recall: number) => 224 - recall * 180;
  return <figure>
    <svg className="inspector-scale-chart" role="img" aria-label="Measured recall versus server time. The exact values are in the table below." viewBox="0 0 650 280">
      {[0, 0.5, 1].map((value) => <g key={value}><line x1={56} x2={616} y1={y(value)} y2={y(value)} /><text x={6} y={y(value) + 4}>{value * 100}%</text></g>)}
      <polyline points={points.map((point) => `${x(point.server_ms)},${y(point.recall_at_k)}`).join(" ")} />
      {points.map((point) => <circle key={point.ef_search} cx={x(point.server_ms)} cy={y(point.recall_at_k)} r={4}><title>ef_search {point.ef_search}: {point.server_ms} ms, {(point.recall_at_k * 100).toFixed(1)}% recall</title></circle>)}
      <text x={56} y={246}>0 ms</text><text x={616} y={246} textAnchor="end">{maxTime.toFixed(1)} ms</text><text x={336} y={273} textAnchor="middle">Server time · each dot is a measured ef_search setting</text>
    </svg>
    <figcaption className="inspector-note">Recall against exact nearest neighbors{measured.provenance.k ? ` at k = ${measured.provenance.k}` : ""}. The line connects measurements; intermediate values were not tested.</figcaption>
  </figure>;
}

function RepresentationComparison({ measured }: { measured: HnswMeasured | null }) {
  const representations = measured?.representations;
  const operatingPoint = representations?.blog_operating_point;
  return <InspectorSection id="scale-representations" number="04" title="Make the index smaller" description="Optional advanced exploration. Keep Alex’s request and the same embeddings; change how the vector arm stores and finds candidates.">
    <div className="inspector-table-scroll" role="region" aria-label="Vector representation choices" tabIndex={0}>
      <table className="inspector-table"><thead><tr><th>Representation</th><th>PostgreSQL mechanism</th><th>When to explore it</th></tr></thead><tbody>
        <tr><th scope="row">Full precision</th><td><code>vector</code> + <code>vector_cosine_ops</code></td><td>Start here; measure recall and the working set.</td></tr>
        <tr><th scope="row">Half precision</th><td><code>halfvec</code> cast + <code>halfvec_cosine_ops</code></td><td>Try a smaller index while retaining magnitude information.</td></tr>
        <tr><th scope="row">Binary, two passes</th><td><code>binary_quantize</code> + <code>bit_hamming_ops</code>, then exact cosine</td><td>Test candidate depth when index memory becomes the constraint.</td></tr>
      </tbody></table>
    </div>
    <p>Half precision uses 16 bits per dimension; binary keeps one sign bit. Index pages and graph links add overhead, so measure the actual index size. Retain the original vectors for exact rescoring.</p>
    <div className="inspector-network" aria-label="Binary vector retrieval flow"><span>Hamming candidates</span><ArrowRight aria-hidden="true" size={18} /><span>Exact cosine rescore</span><ArrowRight aria-hidden="true" size={18} /><span>Vector shortlist</span><ArrowRight aria-hidden="true" size={18} /><span>RRF → Cohere Rerank</span></div>
    <p className="inspector-note">Exact cosine rescoring repairs order inside the retrieved pool. It cannot recover missing candidates. Cohere Rerank comes later and scores the query against product text; these are different operations.</p>
    {representations && measured ? <>
      <p className="inspector-note"><strong>{measured.attribution.attributed ? "Recorded comparison" : "Historical comparison · different catalog revision"}</strong> · {representations.anchors} anchors · recall@{representations.k} against exact fp32 neighbors · ef_search {representations.ef_search}. These casts use the same embeddings, with no re-embedding.</p>
      <div className="inspector-table-scroll" role="region" aria-label="Recorded representation measurements" tabIndex={0}><table className="inspector-table"><thead><tr><th>Representation</th><th>Candidates to rescore</th><th>Index size</th><th>Recall@{representations.k}</th><th>Server time</th></tr></thead><tbody>{representations.rows.map((row) => <tr key={`${row.representation}-${row.overfetch}`}><th scope="row">{row.representation === "binary_two_pass" ? "Binary + cosine" : row.representation === "halfvec" ? "halfvec" : "fp32"}</th><td>{row.overfetch ?? "—"}</td><td>{formatBytes(row.index_size_bytes)}</td><td>{(row.recall_at_k * 100).toFixed(2)}%</td><td>{row.server_ms} ms</td></tr>)}</tbody></table></div>
      {operatingPoint ? <InspectorDetail title="What happens with a deeper binary candidate pool?">
        <p>Compare the recorded operating points below. More candidates recovered recall here at higher server cost. This experiment does not establish how either index behaves under memory pressure or with a full workshop room.</p>
        <div className="inspector-table-scroll" role="region" aria-label="Deep binary candidate measurements" tabIndex={0}><table className="inspector-table"><thead><tr><th>Recorded configuration</th><th>Recall@{operatingPoint.k}</th><th>Server time</th><th>Buffer hits</th></tr></thead><tbody>{operatingPoint.rows.map((row) => <tr key={row.config}><th scope="row">{row.config}</th><td>{(row.recall_at_k * 100).toFixed(2)}%</td><td>{row.server_ms} ms</td><td>{row.shared_hit_blocks.toLocaleString()}</td></tr>)}</tbody></table></div>
        <p className="inspector-note">The configurations use different search effort. A recall improvement here is not evidence that binary universally beats fp32. Candidate depth above ef_search needs iterative scanning; inspect the actual plan and returned candidate count.</p>
      </InspectorDetail> : null}
      <InspectorDetail title="Where these measurements came from"><p>{measured.attribution.attribution_note}</p><CodeBlock label="Representation record" code={JSON.stringify({ captured_at: measured.captured_at, provenance: measured.provenance, rows: representations.rows }, null, 2)} /></InspectorDetail>
    </> : <p className="inspector-note">{measured?.representations_unavailable_reason ?? "Representation measurements are not available. The choices above describe the mechanisms, without claiming a measured result."}</p>}
    <p className="inspector-note">Keep this after the core Retrieve → Rank → Reason mission. Compare exact recall, filtered recall, index size and concurrent latency before selecting an index. <a href="https://aws.amazon.com/blogs/database/scale-pgvector-with-binary-quantization-on-amazon-aurora-postgresql/" target="_blank" rel="noreferrer">Read the AWS binary quantization study</a> and <a href="https://github.com/pgvector/pgvector#half-precision-indexing" target="_blank" rel="noreferrer">pgvector’s expression-index examples</a>.</p>
  </InspectorSection>;
}

function ScaleInspector() {
  const [substrate, setSubstrate] = useState<HnswSubstrate | null>(null);
  const [measured, setMeasured] = useState<HnswMeasured | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setPending(true);
    setErrors([]);
    void Promise.allSettled([api.hnswSubstrate(), api.hnswMeasured()]).then(([live, record]) => {
      if (!active) return;
      const failures: string[] = [];
      if (live.status === "fulfilled") setSubstrate(live.value);
      else failures.push(`Current index could not load: ${live.reason instanceof Error ? live.reason.message : "unknown error"}`);
      if (record.status === "fulfilled") setMeasured(record.value);
      else failures.push(`Recorded measurements could not load: ${record.reason instanceof Error ? record.reason.message : "unknown error"}`);
      setErrors(failures);
      setPending(false);
    });
    return () => { active = false; };
  }, [attempt]);

  return <div className="page pipeline-inspector">
    <MosaicLabsTabs active="hnsw" />
    <div className="inspector-intro"><MosaicLabsMasthead title={<>A small shortlist.<br />A much larger search.</>} deck="HNSW helps the meaning arm find nearby vectors without comparing every product. Explore the index behind Mosaic, then inspect the measured tradeoffs." /></div>
    {pending ? <p role="status">Reading the index and its recorded measurements…</p> : null}
    {errors.length ? <div className="inspector-error" role="alert">{errors.map((error) => <p key={error}>{error}</p>)}<button type="button" className="text-button" onClick={() => setAttempt((value) => value + 1)}>Retry loading</button></div> : null}
    <InspectorSection id="scale-mechanism" number="01" title="How it finds neighbors" description="HNSW is an approximate index over embeddings. Its graph narrows the search before products enter the shared ranking pipeline.">
      <div className="inspector-network"><span>Query embedding</span><ArrowRight aria-hidden="true" size={18} /><span>Coarse graph layers</span><ArrowRight aria-hidden="true" size={18} /><span>Nearby candidates</span><ArrowRight aria-hidden="true" size={18} /><span>RRF</span></div>
      <p>The search descends from sparse upper layers to a denser neighborhood. <code>ef_search</code> controls search effort; <code>m</code> and <code>ef_construction</code> shape the graph when it is built.</p>
      <p className="inspector-note">Conceptual flow. PostgreSQL does not expose the actual graph traversal in these records.</p>
      <p className="inspector-note"><a href="https://github.com/pgvector/pgvector#hnsw" target="_blank" rel="noreferrer">Read the pgvector HNSW documentation</a></p>
      {substrate ? <>
        <dl className="inspector-facts"><div><dt>Vectors in the connected cluster</dt><dd>{substrate.corpus.vector_count.toLocaleString()}</dd></div><div><dt>Embedding dimensions</dt><dd>{substrate.corpus.dimensions ?? "Not reported"}</dd></div><div><dt>HNSW index size</dt><dd>{formatBytes(substrate.index.size_bytes)}</dd></div><div><dt>Storage per vector, including index overhead</dt><dd>{formatBytes(substrate.index.bytes_per_vector)}</dd></div><div><dt>pgvector version</dt><dd>{substrate.aurora.vector_extension_version ?? "Not reported"}</dd></div></dl>
        <InspectorDetail title="Current index definition & database settings"><CodeBlock label="Index definition" code={substrate.index.definition} /><CodeBlock label="Current database" code={JSON.stringify({ settings: substrate.settings, aurora: substrate.aurora }, null, 2)} /><p className="inspector-note">These are current database settings. A search receipt is the authority for the settings applied to that particular request.</p></InspectorDetail>
      </> : null}
    </InspectorSection>
    <InspectorSection id="scale-recall" number="02" title="Measure the tradeoff" description="More search effort can recover more neighbors. Measure recall, time and buffers together to find a useful operating point.">
      {measured ? <>
        <p className="inspector-note"><strong>{measured.attribution.attributed ? "Recorded measurement" : "Measured elsewhere"}</strong> · Captured {new Date(measured.captured_at).toLocaleDateString("en-GB")}. {measured.attribution.attribution_note}</p>
        <RecallPlot measured={measured} />
        <div className="inspector-table-scroll" role="region" aria-label="Measured HNSW tradeoffs" tabIndex={0}><table className="inspector-table"><thead><tr><th>ef_search</th><th>Recall</th><th>Server time</th><th>Buffer hits</th></tr></thead><tbody>{measured.ef_sweep.map((point) => <tr key={point.ef_search}><th scope="row">{point.ef_search}</th><td>{(point.recall_at_k * 100).toFixed(1)}%</td><td>{point.server_ms} ms</td><td>{point.shared_hit_blocks.toLocaleString()}</td></tr>)}</tbody></table></div>
        <p className="inspector-note">Exact baseline: {measured.exact_baseline.p50_ms} ms p50 · {measured.exact_baseline.node} · {measured.exact_baseline.method}. These are recorded server measurements, not end-to-end or concurrent-user latency.</p>
        <InspectorDetail title="Where these measurements came from"><CodeBlock label="Measurement source" code={JSON.stringify({ captured_at: measured.captured_at, provenance: measured.provenance, attribution: measured.attribution, index: measured.index }, null, 2)} /></InspectorDetail>
      </> : <p className="inspector-waiting">A recorded sweep is needed to show the recall and latency tradeoff.</p>}
    </InspectorSection>
    <InspectorSection id="scale-filters" number="03" title="Keep filters in the test" description="A neighbor can be close in meaning and still fail a price, category or specification constraint. Selective filters change the work the index needs to do.">
      <p>When filtering removes nearby candidates, iterative scans can continue searching. Inspect returned rows and recall against the same filtered exact baseline.</p>
      {measured ? <InspectorDetail title="Recorded filter and scan comparisons"><div className="inspector-table-scroll" role="region" aria-label="Filtered HNSW measurements" tabIndex={0}><table className="inspector-table"><thead><tr><th>Filter</th><th>Matching rows</th><th>Scan mode</th><th>Memory</th><th>Returned</th><th>Recall</th><th>Time</th></tr></thead><tbody>{measured.filter_matrix.flatMap((level) => level.modes.map((mode) => <tr key={`${level.preset}-${mode.iterative_scan}-${mode.scan_mem_multiplier}`}><th scope="row">{level.label}</th><td>{level.matching_rows.toLocaleString()}</td><td>{mode.iterative_scan}</td><td>{mode.scan_mem_mb} MB</td><td>{mode.rows_returned}</td><td>{(mode.recall_at_k * 100).toFixed(1)}%</td><td>{mode.server_ms} ms</td></tr>))}</tbody></table></div></InspectorDetail> : null}
      <ol className="inspector-lessons"><li><h3>Keep the partial-index predicate</h3><p>The query must satisfy the index predicate. Compare plans with <code>EXPLAIN (ANALYZE, BUFFERS)</code>; a missing predicate can turn a neighbor lookup into a scan.</p>{measured ? <p className="inspector-note">Recorded missing-predicate case: {measured.missing_predicate.node}, {measured.missing_predicate.server_ms} ms.</p> : null}</li><li><h3>Test the settings the service uses</h3><p>Use <code>mosaic_search.configure_hnsw</code> for probes as well as requests. Inspect scan mode, tuple limits and the memory budget together.</p></li><li><h3>Measure a room, not just a request</h3><p>For workshop capacity, test concurrent requests and report p95 latency, errors and model throttling. A single-query index benchmark does not establish capacity for the whole room.</p></li></ol>
    </InspectorSection>
    <RepresentationComparison measured={measured} />
    <aside className="inspector-scale-link"><div><h2>Look closer at the measurements.</h2><p>The advanced instrument retains the live probes, vector representations and scale experiments.</p></div><Link href="/mosaic-labs/hnsw?view=bench">Open advanced instrument <ArrowRight size={18} aria-hidden="true" /></Link></aside>
  </div>;
}

export function ScaleInspectorPage() {
  const [params] = useSearchParams();
  return params.get("view") === "bench" ? <PerformancePage /> : <ScaleInspector />;
}
