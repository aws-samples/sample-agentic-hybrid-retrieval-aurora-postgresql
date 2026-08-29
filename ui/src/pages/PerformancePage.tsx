import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Database,
  HardDrive,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [anchorsLoading, setAnchorsLoading] = useState(true);
  const [anchorsError, setAnchorsError] = useState("");
  const [neighborhood, setNeighborhood] = useState<HnswNeighborhood | null>(null);
  const [neighborhoodLoading, setNeighborhoodLoading] = useState(false);
  const [neighborhoodError, setNeighborhoodError] = useState("");
  const [neighborhoodRetry, setNeighborhoodRetry] = useState(0);
  const [projection, setProjection] = useState<BenchmarkProjection | null>(null);
  const [projectionLoading, setProjectionLoading] = useState(true);
  const [projectionError, setProjectionError] = useState("");
  const [coreLoading, setCoreLoading] = useState(true);
  const [error, setError] = useState("");

  const [efSearch, setEfSearch] = useState<number | null>(null);
  const [anchorId, setAnchorId] = useState<number | null>(null);
  const [preset, setPreset] = useState("none");
  const [scan, setScan] = useState<HnswFilterMode["iterative_scan"]>("relaxed_order");
  const [scanMemMb, setScanMemMb] = useState<number | null>(null);

  const [probe, setProbe] = useState<HnswProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState("");
  const coreRequestVersion = useRef(0);
  const anchorsRequestVersion = useRef(0);
  const projectionRequestVersion = useRef(0);
  const probeRequestVersion = useRef(0);
  const probeController = useRef<AbortController | null>(null);

  const loadCore = useCallback(() => {
    const version = coreRequestVersion.current + 1;
    coreRequestVersion.current = version;
    setCoreLoading(true);
    setError("");
    Promise.all([
      api.readiness(),
      api.hnswMeasured(),
      api.hnswSubstrate(),
    ])
      .then(([nextReadiness, nextMeasured, nextSubstrate]) => {
        if (version !== coreRequestVersion.current) return;
        setReadiness(nextReadiness);
        setMeasured(nextMeasured);
        setSubstrate(nextSubstrate);
        setEfSearch(
          nextMeasured.ef_sweep.find((point) => point.ef_search === SERVED_EF_SEARCH)
            ?.ef_search ??
            nextMeasured.ef_sweep[0]?.ef_search ??
            null,
        );
        setScanMemMb(nextMeasured.filter_matrix[0]?.modes[0]?.scan_mem_mb ?? null);
      })
      .catch((cause: unknown) => {
        if (version !== coreRequestVersion.current) return;
        setError(
          cause instanceof Error ? cause.message : "The HNSW instrument could not load",
        );
      })
      .finally(() => {
        if (version === coreRequestVersion.current) setCoreLoading(false);
      });
  }, []);

  const loadAnchors = useCallback(() => {
    const version = anchorsRequestVersion.current + 1;
    anchorsRequestVersion.current = version;
    setAnchorsLoading(true);
    setAnchorsError("");
    api
      .hnswAnchors()
      .then((nextAnchors) => {
        if (version !== anchorsRequestVersion.current) return;
        setAnchors(nextAnchors);
        setAnchorId((current) => (
          current !== null
          && nextAnchors.some((anchor) => anchor.product_id === current)
            ? current
            : nextAnchors[0]?.product_id ?? null
        ));
        if (!nextAnchors.length) {
          setAnchorsError("No HNSW probe anchors are available for this dataset.");
        }
      })
      .catch((cause: unknown) => {
        if (version !== anchorsRequestVersion.current) return;
        setAnchors([]);
        setAnchorId(null);
        setAnchorsError(
          cause instanceof Error ? cause.message : "HNSW probe anchors are unavailable",
        );
      })
      .finally(() => {
        if (version === anchorsRequestVersion.current) setAnchorsLoading(false);
      });
  }, []);

  const loadProjection = useCallback(() => {
    const version = projectionRequestVersion.current + 1;
    projectionRequestVersion.current = version;
    setProjectionLoading(true);
    setProjectionError("");
    api
      .projection()
      .then((nextProjection) => {
        if (version !== projectionRequestVersion.current) return;
        setProjection(nextProjection);
      })
      .catch((cause: unknown) => {
        if (version !== projectionRequestVersion.current) return;
        setProjection(null);
        setProjectionError(
          cause instanceof Error ? cause.message : "The scale projection is unavailable",
        );
      })
      .finally(() => {
        if (version === projectionRequestVersion.current) {
          setProjectionLoading(false);
        }
      });
  }, []);

  useEffect(() => {
    loadCore();
    loadAnchors();
    loadProjection();
    return () => {
      coreRequestVersion.current += 1;
      anchorsRequestVersion.current += 1;
      projectionRequestVersion.current += 1;
      probeRequestVersion.current += 1;
      probeController.current?.abort();
    };
  }, [loadAnchors, loadCore, loadProjection]);

  /**
   * The exact-neighbour ring for the selected anchor, and only that.
   *
   * This used to write the page-level `error`, which the early return below turns
   * into a full-page error state. One 503 from this endpoint - the shape it fails
   * in when `mosaic_bench.exact_neighbor` has no rows for the connected dataset
   * manifest - therefore discarded the substrate sizes, the measured sweep, the
   * anchors, and the projection that had all loaded successfully, and the page
   * rendered nothing but the message. Ground truth is one panel's input.
   */
  useEffect(() => {
    if (anchorId === null) {
      setNeighborhood(null);
      setNeighborhoodLoading(false);
      setNeighborhoodError("");
      return;
    }
    let active = true;
    setNeighborhood(null);
    setNeighborhoodLoading(true);
    setNeighborhoodError("");
    api
      .hnswNeighborhood(anchorId, "none", 10)
      .then((next) => {
        if (active) {
          setNeighborhood(next);
          setNeighborhoodError("");
          setNeighborhoodLoading(false);
        }
      })
      .catch((cause: Error) => {
        if (active) {
          setNeighborhood(null);
          setNeighborhoodError(cause.message);
          setNeighborhoodLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [anchorId, neighborhoodRetry]);

  // A new anchor, operating point, or filter invalidates the previous probe. Leaving it
  // on screen would attribute one query's result to a different query.
  useEffect(() => {
    probeRequestVersion.current += 1;
    probeController.current?.abort();
    probeController.current = null;
    setProbe(null);
    setProbeError("");
    setProbing(false);
  }, [anchorId, efSearch, preset, scan]);

  const runProbe = useCallback(() => {
    if (anchorId === null || efSearch === null) {
      setProbeError("Load a probe anchor before running a live HNSW query.");
      return;
    }
    probeController.current?.abort();
    const controller = new AbortController();
    probeController.current = controller;
    const version = probeRequestVersion.current + 1;
    probeRequestVersion.current = version;
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
      }, controller.signal)
      .then((nextProbe) => {
        if (version === probeRequestVersion.current) setProbe(nextProbe);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || version !== probeRequestVersion.current) return;
        setProbeError(cause instanceof Error ? cause.message : "The HNSW probe failed");
      })
      .finally(() => {
        if (version !== probeRequestVersion.current) return;
        setProbing(false);
        if (probeController.current === controller) probeController.current = null;
      });
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
    if (error) return <ErrorState message={error} onRetry={loadCore} />;
    if (coreLoading || !readiness || !measured || !substrate || efSearch === null) {
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

        {anchorsLoading ? (
          <LoadingState label="Loading HNSW probe anchors" />
        ) : anchorsError ? (
          <section className="hnsw-neighborhood-unavailable" aria-live="polite">
            <h2>Live probe anchors are unavailable.</h2>
            <ErrorState message={anchorsError} onRetry={loadAnchors} />
          </section>
        ) : neighborhood ? (
          <HnswNeighborhoodRing
            anchors={anchors}
            efSearch={efSearch}
            neighborhood={neighborhood}
            onAnchorChange={setAnchorId}
            probe={probe}
          />
        ) : neighborhoodError ? (
          <section className="hnsw-neighborhood-unavailable" aria-live="polite">
            <h2>Exact neighbours are unavailable for this anchor.</h2>
            <ErrorState
              message={neighborhoodError}
              onRetry={() => setNeighborhoodRetry((current) => current + 1)}
            />
          </section>
        ) : neighborhoodLoading ? (
          <LoadingState label="Loading exact HNSW neighbours" />
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

        {projection ? (
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
        ) : projectionError ? (
          <section className="hnsw-neighborhood-unavailable" aria-live="polite">
            <h2>Scale projection is unavailable.</h2>
            <ErrorState message={projectionError} onRetry={loadProjection} />
          </section>
        ) : projectionLoading ? (
          <LoadingState label="Loading the scale projection" />
        ) : null}

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

        <nav className="hnsw-next" aria-label="Other Playground lenses">
          <Link href="/labs/retrieval">
            <ArrowLeft aria-hidden="true" size={16} /> Retrieve, rank, reason
          </Link>
          <Link href="/mosaic-labs/studio">
            Catalog studio <ArrowRight aria-hidden="true" size={16} />
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
