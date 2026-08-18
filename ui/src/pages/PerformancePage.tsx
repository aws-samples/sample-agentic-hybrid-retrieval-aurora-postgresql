import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Database,
  HardDrive,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { HnswControlledAb } from "../components/HnswControlledAb";
import { HnswFilterMatrix } from "../components/HnswFilterMatrix";
import { HnswNeighborhoodRing } from "../components/HnswNeighborhoodRing";
import { HnswParetoCurve } from "../components/HnswParetoCurve";
import { HnswRepresentations } from "../components/HnswRepresentations";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { ErrorState, LoadingState } from "../components/States";
import { formatBytes, storageSegments } from "../hnsw";
import type {
  BenchmarkProjection,
  HnswFilterMode,
  HnswMeasured,
  HnswNeighborhood,
  HnswProbe,
  HnswProduct,
  HnswSubstrate,
  ReadinessResponse,
} from "../types";

const hnswIndexName = "product_document_embedding_hnsw_cosine_idx";
const SERVED_EF_SEARCH = 100;

/**
 * What the measurements changed about how to operate the index.
 *
 * Each card cites the number it came from. The three cards that used to sit here were
 * generic advice with nothing measured behind any of them.
 */
function productionLessons(measured: HnswMeasured, saturationEfSearch: number | null) {
  const slowest = measured.ef_sweep.at(-1);
  const saturated = measured.ef_sweep.find(
    (point) => point.ef_search === saturationEfSearch,
  );
  return [
    {
      title: "Repeat the partial-index predicate",
      detail:
        `The index is partial. Drop embedding IS NOT NULL and the same query becomes a ` +
        `${measured.missing_predicate.node} over every row at ` +
        `${measured.missing_predicate.server_ms} ms, which is ` +
        `${measured.missing_predicate.slowdown_factor}x the served operating point, for ` +
        `identical output.`,
    },
    {
      title:
        saturationEfSearch === null
          ? "Find where recall stops improving"
          : `Stop at ef_search ${saturationEfSearch}`,
      detail:
        saturated && slowest
          ? `Recall reaches ${(saturated.recall_at_k * 100).toFixed(1)}% there. ef_search ` +
            `${slowest.ef_search} spends ` +
            `${(slowest.shared_hit_blocks / saturated.shared_hit_blocks).toFixed(1)}x the ` +
            `buffers to reach the same number.`
          : "Sweep it against exact ground truth rather than assuming higher is better.",
    },
    {
      title: "Raise the memory budget, not the tuple cap",
      detail:
        "Under a selective filter, max_scan_tuples measured identically at 20K, 100K, " +
        "500K and 1M. The limit that binds is work_mem times scan_mem_multiplier.",
    },
  ];
}

export function PerformancePage() {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [measured, setMeasured] = useState<HnswMeasured | null>(null);
  const [substrate, setSubstrate] = useState<HnswSubstrate | null>(null);
  const [anchors, setAnchors] = useState<HnswProduct[]>([]);
  const [neighborhood, setNeighborhood] = useState<HnswNeighborhood | null>(null);
  const [projection, setProjection] = useState<BenchmarkProjection | null>(null);
  const [error, setError] = useState("");

  const [efSearch, setEfSearch] = useState<number | null>(null);
  const [anchorId, setAnchorId] = useState<number | null>(null);
  const [preset, setPreset] = useState("none");
  const [scan, setScan] = useState<HnswFilterMode["iterative_scan"]>("relaxed_order");
  const [scanMemMb, setScanMemMb] = useState<number | null>(null);

  const [probe, setProbe] = useState<HnswProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      api.readiness(),
      api.hnswMeasured(),
      api.hnswSubstrate(),
      api.hnswAnchors(),
      api.projection(),
    ])
      .then(([nextReadiness, nextMeasured, nextSubstrate, nextAnchors, nextProjection]) => {
        if (!active) return;
        setReadiness(nextReadiness);
        setMeasured(nextMeasured);
        setSubstrate(nextSubstrate);
        setAnchors(nextAnchors);
        setProjection(nextProjection);
        setEfSearch(
          nextMeasured.ef_sweep.find((point) => point.ef_search === SERVED_EF_SEARCH)
            ?.ef_search ??
            nextMeasured.ef_sweep[0]?.ef_search ??
            null,
        );
        setAnchorId(nextAnchors[0]?.product_id ?? null);
        setScanMemMb(nextMeasured.filter_matrix[0]?.modes[0]?.scan_mem_mb ?? null);
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (anchorId === null) return;
    let active = true;
    api
      .hnswNeighborhood(anchorId, "none", 10)
      .then((next) => {
        if (active) setNeighborhood(next);
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      });
    return () => {
      active = false;
    };
  }, [anchorId]);

  // A new anchor, operating point, or filter invalidates the previous probe. Leaving it
  // on screen would attribute one query's result to a different query.
  useEffect(() => {
    setProbe(null);
    setProbeError("");
  }, [anchorId, efSearch, preset]);

  const runProbe = useCallback(() => {
    if (anchorId === null || efSearch === null) return;
    setProbing(true);
    setProbeError("");
    api
      // scan_mem_multiplier and max_scan_tuples are omitted deliberately: the endpoint
      // resolves them from db/config/retrieval.yaml. Sending them from here would be a
      // second declaration of a served number.
      .hnswProbe({
        anchor_product_id: anchorId,
        ef_search: efSearch,
        iterative_scan: scan,
        filter_preset: preset,
        k: 10,
      })
      .then(setProbe)
      .catch((cause: Error) => setProbeError(cause.message))
      .finally(() => setProbing(false));
  }, [anchorId, efSearch, preset, scan]);

  const saturationEfSearch = useMemo(() => {
    if (!measured || measured.ef_sweep.length === 0) return null;
    const best = Math.max(...measured.ef_sweep.map((point) => point.recall_at_k));
    return Math.min(
      ...measured.ef_sweep
        .filter((point) => point.recall_at_k === best)
        .map((point) => point.ef_search),
    );
  }, [measured]);

  const content = (() => {
    if (error) return <ErrorState message={error} />;
    if (!readiness || !measured || !substrate || !projection || efSearch === null) {
      return <LoadingState label="Reading the live Aurora index and measured sweep" />;
    }

    const { database } = readiness;
    const hnswIndexReady = !database.missing_retrieval_indexes?.includes(hnswIndexName);
    const segments = storageSegments(substrate.storage);
    const workMemMb = Number.parseInt(substrate.settings.work_mem ?? "4", 10) || 4;

    return (
      <>
        <section className="hnsw-live" aria-labelledby="hnsw-live-title">
          <header>
            <div>
              <h2 id="hnsw-live-title">What the index actually costs.</h2>
              <p>
                Read from the connected cluster on this request. Every size below matches
                what <code>pg_size_pretty</code> prints for the same relation.
              </p>
            </div>
            <span className="hnsw-evidence-badge live">LIVE AURORA INDEX</span>
          </header>

          <div className="hnsw-live-facts">
            <div>
              <strong className="hnsw-live-value hnsw-live-value--metric">
                {substrate.corpus.vector_count.toLocaleString()}
              </strong>
              <span>vectors indexed</span>
            </div>
            <div>
              <strong className="hnsw-live-value hnsw-live-value--metadata">
                PostgreSQL {substrate.aurora.database_version}
              </strong>
              <span>Aurora engine</span>
            </div>
            <div>
              <strong className="hnsw-live-value hnsw-live-value--metadata">
                {substrate.aurora.vector_extension_version
                  ? `pgvector ${substrate.aurora.vector_extension_version}`
                  : "pgvector unavailable"}
              </strong>
              <span>vector extension</span>
            </div>
            <div>
              <strong className="hnsw-live-value hnsw-live-value--metadata">
                {substrate.corpus.dimensions
                  ? `${substrate.corpus.dimensions.toLocaleString()} dimensions`
                  : "Dimensions unavailable"}
              </strong>
              <span>Cohere Embed v4 vectors</span>
            </div>
            <div>
              <strong className="hnsw-live-value hnsw-live-value--config">
                m={measured.index.m} / ef_construction={measured.index.ef_construction}
              </strong>
              <span>build parameters</span>
            </div>
          </div>

          <div className="hnsw-storage">
            <div className="hnsw-storage-headline">
              <HardDrive aria-hidden="true" size={18} />
              <strong>{formatBytes(substrate.index.size_bytes)}</strong>
              <span>
                of HNSW index over {formatBytes(substrate.storage.heap_bytes)} of heap
              </span>
            </div>
            <div
              aria-label="Storage split of mosaic_search.product_document"
              className="hnsw-storage-bar"
              role="img"
            >
              {segments.map((segment) => (
                <i
                  className={`segment-${segment.key}`}
                  key={segment.key}
                  style={{ width: `${segment.percent}%` }}
                  title={`${segment.label}: ${formatBytes(segment.bytes)} (${segment.percent}%)`}
                />
              ))}
            </div>
            <ul className="hnsw-storage-legend">
              {segments.map((segment) => (
                <li className={`segment-${segment.key}`} key={segment.key}>
                  <i aria-hidden="true" />
                  <span className="hnsw-storage-legend-label">{segment.label}</span>
                  <span className="hnsw-storage-legend-metric">
                    <strong>{formatBytes(segment.bytes)}</strong>
                    <small>{segment.percent}% of total</small>
                  </span>
                </li>
              ))}
            </ul>
            <p className="hnsw-storage-note">
              <strong>
                {substrate.index.bytes_per_vector.toLocaleString()} bytes per vector
              </strong>{" "}
              against a {substrate.index.fp32_payload_bytes.toLocaleString()}-byte fp32
              payload. That is {substrate.index.overhead_factor}x overhead at m=
              {measured.index.m}.
              The index is larger than the TOAST that stores the vectors it indexes.
              Relation overhead covers TOAST indexes and auxiliary relation forks.
            </p>
          </div>

          <footer className={hnswIndexReady ? "" : "blocked"}>
            {hnswIndexReady ? (
              <CheckCircle2 aria-hidden="true" size={18} />
            ) : (
              <CircleAlert aria-hidden="true" size={18} />
            )}
            <span>
              <strong>
                {hnswIndexReady ? "HNSW index ready" : "HNSW index unavailable"}
              </strong>
              <code>{hnswIndexName}</code>
            </span>
            <small>{database.database_name}</small>
          </footer>
        </section>

        {measured.representations ? (
          <HnswRepresentations
            fp32SizeBytes={substrate.index.size_bytes}
            representations={measured.representations}
          />
        ) : null}

        <HnswParetoCurve
          efSearch={efSearch}
          measured={measured}
          onEfChange={setEfSearch}
          onProbe={runProbe}
          probe={probe}
          probeError={probeError}
          probing={probing}
        />

        {neighborhood ? (
          <HnswNeighborhoodRing
            anchors={anchors}
            efSearch={efSearch}
            neighborhood={neighborhood}
            onAnchorChange={setAnchorId}
            probe={probe}
          />
        ) : null}

        {measured.filter_matrix.length > 0 && scanMemMb !== null ? (
          <HnswFilterMatrix
            levels={measured.filter_matrix}
            onPresetChange={setPreset}
            onScanChange={setScan}
            onScanMemChange={setScanMemMb}
            preset={preset}
            scan={scan}
            scanMemMb={scanMemMb}
            workMemMb={workMemMb}
          />
        ) : null}

        <section className="hnsw-envelope" aria-labelledby="hnsw-envelope-title">
          <header>
            <div>
              <h2 id="hnsw-envelope-title">
                Where this goes at ten and a hundred million.
              </h2>
              <p>
                Extrapolated from the measured 500K row above. Index size is arithmetic at{" "}
                {projection.assumptions.bytes_per_vector.toLocaleString()} bytes per vector;
                latency and recall use the stated growth assumptions.
              </p>
            </div>
            <span className="hnsw-evidence-badge projected">
              PROJECTED FROM 500K BASELINE
            </span>
          </header>

          <div
            aria-label="Projected HNSW scale envelope"
            className="hnsw-table-scroll"
            role="region"
            tabIndex={0}
          >
            <table className="hnsw-envelope-table">
              <thead>
                <tr>
                  <th scope="col">Catalog</th>
                  <th scope="col">Projected p95</th>
                  <th scope="col">Projected Recall@10</th>
                  <th scope="col">Projected index</th>
                </tr>
              </thead>
              <tbody>
                {projection.rows.map((row) => (
                  <tr
                    className={row.scale === 500_000 ? "baseline" : undefined}
                    key={row.scale}
                  >
                    <th scope="row">
                      <Database aria-hidden="true" size={15} />
                      {row.scale >= 1_000_000
                        ? `${row.scale / 1_000_000}M`
                        : `${row.scale / 1_000}K`}
                      {row.scale === 500_000 ? <em>measured</em> : null}
                    </th>
                    <td>{row.p95_latency_ms.toFixed(2)} ms</td>
                    <td>{(row.recall_at_10 * 100).toFixed(2)}%</td>
                    <td>
                      {row.index_size_gb.toLocaleString(undefined, {
                        maximumFractionDigits: 1,
                      })}{" "}
                      GB
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <footer>
            <code>{projection.assumptions.latency_growth}</code>
            <code>{projection.assumptions.recall_decay}</code>
            <code>index: {projection.assumptions.index_size_growth}</code>
          </footer>

          {measured.local_nvme ? (
            <p className="hnsw-envelope-crossover">{measured.local_nvme.crossover_wording}</p>
          ) : null}
        </section>

        {measured.local_nvme ? <HnswControlledAb nvme={measured.local_nvme} /> : null}

        <section className="hnsw-production" aria-labelledby="hnsw-production-title">
          <header>
            <h2 id="hnsw-production-title">What the measurements changed.</h2>
            <p>Three operating decisions, each traceable to a number above.</p>
          </header>
          <div>
            {productionLessons(measured, saturationEfSearch).map((lesson) => (
              <article key={lesson.title}>
                <CheckCircle2 aria-hidden="true" size={18} />
                <strong>{lesson.title}</strong>
                <p>{lesson.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <nav className="hnsw-next" aria-label="Continue through Mosaic Labs">
          <Link href="/mosaic-labs">
            <ArrowLeft aria-hidden="true" size={16} /> Explore Labs
          </Link>
          <Link href="/mosaic-labs/studio">
            Open Studio <ArrowRight aria-hidden="true" size={16} />
          </Link>
        </nav>
      </>
    );
  })();

  return (
    <div className="page mosaic-labs-page labs-premium hnsw-page">
      <MosaicLabsTabs active="hnsw" />
      <MosaicLabsMasthead
        deck="Measure the index against exact ground truth, watch recall stop improving, and find the filter that returns nothing while ten matches exist."
        supportingText="Measured on the live 500K corpus. Projections are labelled."
        title="Tune HNSW against ground truth."
      />
      {content}
    </div>
  );
}
