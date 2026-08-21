import { AlertTriangle, LoaderCircle, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { RetrievalDiagnosticsStrip } from "../components/RetrievalDiagnosticsStrip";
import { RetrievalObservatory } from "../components/RetrievalObservatory";
import { SearchRetrievalReceipt } from "../components/RetrievalReceipt";
import { WorkshopProgress } from "../components/WorkshopProgress";
import { mosaicRetrievalExamples, retrievalExamplesByStage } from "../labMissions";
import { liveRetrievalOutcome, retrievalLabOutcome } from "../labOutcome";
import { useSearchParams } from "../navigation";
import type { SearchResponse } from "../types";

type RunMeasurement = {
  label: string;
  value: string;
};

function pipelineFailureMessage(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : "Retrieval failed";
  if (/ExpiredToken|Bedrock credentials are unavailable/i.test(message)) {
    return "The Mosaic API AWS session has expired. Refresh it, restart the API, then retry.";
  }
  if (cause instanceof ApiError && cause.status === 404) {
    return "The active preview is not connected to the Mosaic search API. Point it at Mosaic, then retry.";
  }
  return message;
}

function runMeasurements(
  example: typeof mosaicRetrievalExamples[number],
  response: SearchResponse,
): RunMeasurement[] {
  const targets = response.results.filter((product) =>
    example.target_product_ids.includes(product.product_id),
  );
  const bestPreRerankRank = Math.min(
    ...targets.map((product) => product.signals?.pre_rerank_rank ?? Number.MAX_SAFE_INTEGER),
  );
  const bestFinalRank = Math.min(
    ...targets.map((product) => product.signals?.final_rank ?? Number.MAX_SAFE_INTEGER),
  );
  const formatRank = (rank: number) => (
    !Number.isFinite(rank) || rank === Number.MAX_SAFE_INTEGER ? "Not shown" : `#${rank}`
  );

  return [
    {
      label: "Targets shown",
      value: `${targets.length} / ${example.target_product_ids.length}`,
    },
    {
      label: "Best before rerank",
      value: formatRank(bestPreRerankRank),
    },
    {
      label: "Best final rank",
      value: formatRank(bestFinalRank),
    },
    {
      label: "pg_trgm candidate pool",
      value: String(response.diagnostics?.candidate_counts.trigram_in_pool ?? "Not reported"),
    },
  ];
}

export function RetrievalLabPage() {
  const [params] = useSearchParams();
  const requestedExample = params.get("example") ?? params.get("mission");
  const requestedIndex = mosaicRetrievalExamples.findIndex(
    (example) => example.id === requestedExample,
  );
  const initialIndex = requestedIndex >= 0 ? requestedIndex : 0;
  const [selected, setSelected] = useState(initialIndex);
  const [query, setQuery] = useState(
    () => mosaicRetrievalExamples[initialIndex]?.query ?? "",
  );
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [firstResponse, setFirstResponse] = useState<SearchResponse | null>(null);
  const [executedQuery, setExecutedQuery] = useState("");
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const example = mosaicRetrievalExamples[selected];
  const outcome = useMemo(
    () => {
      if (!response) return null;
      return executedQuery === example.query
        ? retrievalLabOutcome(example, response)
        : liveRetrievalOutcome(response);
    },
    [example, executedQuery, response],
  );
  const firstRunMeasurements = useMemo(
    () => (example && firstResponse ? runMeasurements(example, firstResponse) : []),
    [example, firstResponse],
  );
  const latestRunMeasurements = useMemo(
    () => (example && response ? runMeasurements(example, response) : []),
    [example, response],
  );

  const selectExample = (id: string) => {
    const index = mosaicRetrievalExamples.findIndex((candidate) => candidate.id === id);
    if (index < 0) return;
    requestVersion.current += 1;
    setSelected(index);
    setQuery(mosaicRetrievalExamples[index].query);
    setResponse(null);
    setFirstResponse(null);
    setExecutedQuery("");
    setRunCount(0);
    setError("");
    setLoading(false);
  };

  const editQuery = (value: string) => {
    requestVersion.current += 1;
    setQuery(value);
    setResponse(null);
    setFirstResponse(null);
    setExecutedQuery("");
    setRunCount(0);
    setError("");
    setLoading(false);
  };

  async function run() {
    const requestedQuery = query.trim();
    if (!example || !requestedQuery) return;
    const requestedExample = example;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setError("");
    try {
      const nextResponse = await api.search(
        requestedQuery,
        requestedExample.filters,
        { limit: 12, rerank: true },
      );
      if (version === requestVersion.current) {
        setFirstResponse((first) => first ?? nextResponse);
        setResponse(nextResponse);
        setExecutedQuery(requestedQuery);
        setRunCount((count) => count + 1);
      }
    } catch (cause) {
      if (version === requestVersion.current) {
        setError(pipelineFailureMessage(cause));
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }

  // The same wrapper and masthead the other three Labs views use. This page was
  // the only one still on the generic `.page-header`, whose h1 is 52px at weight
  // 500 against the Labs masthead's 51.84px at 450, and whose heading steps are
  // not the shared `--labs-*` scale at all. That is invisible until the Labs tab
  // strip sits directly above it, which is when two type systems end up stacked in
  // one viewport. `.page-header` is outside the families the type-scale gate
  // inspects, so nothing caught it.
  return (
    <div className="page mosaic-labs-page labs-premium lab-page">
      {/* The same strip the other Labs views carry, so this surface is reachable
          from them and they are reachable from here. */}
      <MosaicLabsTabs active="retrieval" />
      <MosaicLabsMasthead
        action={(
          <form
            className="retrieval-run-action"
            onSubmit={(event) => {
              event.preventDefault();
              void run();
            }}
          >
            {/* Pick, then run. The scenario control used to sit inside the matrix
                below this button, so the order of operations read backwards. */}
            <label className="retrieval-scenario-picker">
              <span>Scenario</span>
              <select
                onChange={(event) => selectExample(event.target.value)}
                value={example?.id ?? ""}
              >
                {retrievalExamplesByStage().map((group) => (
                  <optgroup key={group.stage} label={group.label}>
                    {group.examples.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.discover_label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="retrieval-query-field">
              <span>Query</span>
              <input
                aria-label="Retrieval query"
                autoComplete="off"
                onChange={(event) => editQuery(event.target.value)}
                spellCheck={false}
                type="search"
                value={query}
              />
            </label>
            <button
              className="primary-button"
              type="submit"
              aria-busy={loading}
              disabled={!example || !query.trim() || loading}
            >
              {loading ? (
                <LoaderCircle aria-hidden="true" className="spin" size={17} />
              ) : (
                <Play aria-hidden="true" size={17} fill="currentColor" />
              )}
              {loading ? "Running pipeline" : "Run pipeline"}
            </button>
            {loading ? (
              <span className="retrieval-run-feedback" role="status">
                Embedding, retrieving, fusing, and reranking.
              </span>
            ) : null}
            {error ? (
              <div className="retrieval-run-feedback error">
                <AlertTriangle aria-hidden="true" size={17} />
                <span role="alert">{error}</span>
                <button type="button" className="secondary-button" onClick={() => void run()}>
                  Retry pipeline
                </button>
              </div>
            ) : null}
          </form>
        )}
        deck="Edit a scenario query, run it against Aurora, and compare all five retrieval stages on the same result set."
        title="Retrieval Observatory"
      />

      <WorkshopProgress
        active={example?.stage === "reason" ? "reason" : example?.stage === "rank" ? "rank" : "retrieve"}
      />

      {outcome ? <LabOutcomeBanner outcome={outcome} /> : null}

      <RetrievalObservatory
        example={example}
        loading={loading}
        response={response}
      />

      {response ? <SearchRetrievalReceipt response={response} /> : null}

      {response ? <RetrievalDiagnosticsStrip response={response} /> : null}

      {firstResponse && response && runCount > 1 ? (
        <section className="retrieval-run-comparison" aria-labelledby="retrieval-run-comparison-title">
          <header>
            <div>
              <p className="eyebrow">Live run comparison</p>
              <h2 id="retrieval-run-comparison-title">First run and latest run</h2>
            </div>
            <p>Each value comes from its recorded response.</p>
          </header>
          <div className="retrieval-run-comparison-grid">
            {[
              { label: "First run", measurements: firstRunMeasurements },
              { label: "Latest run", measurements: latestRunMeasurements },
            ].map((snapshot) => (
              <section aria-label={`${snapshot.label} metrics`} key={snapshot.label}>
                <h3>{snapshot.label}</h3>
                <dl>
                  {snapshot.measurements.map((measurement) => (
                    <div key={measurement.label}>
                      <dt>{measurement.label}</dt>
                      <dd>{measurement.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
