import { AlertTriangle, ArrowRightLeft, LoaderCircle, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { FusionDefectLens } from "../components/FusionDefectLens";
import { PackageFinale } from "../components/PackageFinale";
import {
  PlaygroundDisclosure,
  PlaygroundDisclosureShelf,
  PlaygroundDormant,
  PlaygroundFigure,
  PlaygroundFigures,
  PlaygroundStage,
} from "../components/PlaygroundStage";
import { ReasonStage } from "../components/ReasonStage";
import { RepairEvidence } from "../components/RepairEvidence";
import { RetrievalDiagnosticsStrip } from "../components/RetrievalDiagnosticsStrip";
import { RetrievalScorecard } from "../components/RetrievalScorecard";
import { RetrievalObservatory } from "../components/RetrievalObservatory";
import {
  RetrievalChannelMap,
  readChannels,
} from "../components/RetrievalChannelMap";
import {
  CandidateRows,
  PersistedRunDisclosures,
  RrfMath,
} from "../components/RetrievalProvenance";
import { SearchRetrievalReceipt } from "../components/RetrievalReceipt";
import { mosaicRetrievalExamples, retrievalExamplesByStage } from "../labMissions";
import { liveRetrievalOutcome, retrievalLabOutcome } from "../labOutcome";
import {
  RETRIEVAL_SURFACE,
  forwardedSearchFilters,
  useSearchParams,
} from "../navigation";
import { armLanguage } from "../retrievalLanguage";
import type { ReadinessResponse, SearchFilters, SearchResponse } from "../types";

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
      label: "Close spelling in pool",
      value: String(response.diagnostics?.candidate_counts.trigram_in_pool ?? "Not reported"),
    },
  ];
}

/** Eligibility gates the run actually applied, named rather than counted. */
function appliedGates(response: SearchResponse): string[] {
  return Object.entries(response.applied_filters)
    .filter(([, value]) => {
      if (value == null || value === false || value === "") return false;
      if (Array.isArray(value)) return value.length > 0;
      if (typeof value === "object") return Object.keys(value).length > 0;
      return true;
    })
    .map(([name, value]) => `${name.replaceAll("_", " ")}: ${String(value)}`);
}

export function RetrievalLabPage() {
  const [params] = useSearchParams();
  const requestedExample = params.get("example") ?? params.get("mission");
  /**
   * A query on the URL is a shopper's own words, forwarded from Shop.
   *
   * It has to travel with the eligibility gates that were in force when Shop ran
   * it, or the Playground retrieves a different candidate pool and the two screens
   * describe unrelated requests. `run()` used the selected scenario's filters for
   * every run, so a forwarded query was answered under the wrong gates — which is
   * the one thing this hand-off exists to prevent.
   */
  const forwardedQuery = params.get("q")?.trim() ?? "";
  const forwardedFilters = useMemo(
    () => forwardedSearchFilters(params),
    [params],
  );
  const requestedIndex = mosaicRetrievalExamples.findIndex(
    (example) => example.id === requestedExample,
  );
  const initialIndex = requestedIndex >= 0 ? requestedIndex : 0;
  const [selected, setSelected] = useState(initialIndex);
  const [query, setQuery] = useState(
    () => forwardedQuery || mosaicRetrievalExamples[initialIndex]?.query || "",
  );
  /**
   * True while the field still holds the query Shop handed over.
   *
   * Editing it, or picking another scenario, ends the hand-off: from then on the
   * run belongs to the scenario again and uses its gates.
   */
  const [carriedOver, setCarriedOver] = useState(Boolean(forwardedQuery));
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [firstResponse, setFirstResponse] = useState<SearchResponse | null>(null);
  const [executedQuery, setExecutedQuery] = useState("");
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const requestVersion = useRef(0);
  const ranForwarded = useRef(false);
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
  /**
   * Index health, for the one distinction Lab 1 turns on: a trigram GIN index that
   * is present and valid while no candidate in the served pool carries a trigram
   * rank. A failed readiness read leaves it null, and the channel map says the
   * check did not run rather than guessing at an answer.
   */
  useEffect(() => {
    let active = true;
    api
      .readiness()
      .then((value) => {
        if (active) setReadiness(value);
      })
      .catch(() => {
        if (active) setReadiness(null);
      });
    return () => {
      active = false;
    };
  }, []);

  /**
   * Which arms this run was required to produce.
   *
   * `expected_techniques` is a claim about the scenario's own query, so it only
   * applies while the query that ran is that query. A carried-over request from Shop
   * is the shopper's, and asserting "this scenario is written to require the close
   * spelling arm" about someone else's words would let the surface report a
   * disconnected arm on a query that never needed one. Without the requirement a
   * zero count reads as "no candidates for this query", which is all the response
   * can support.
   */
  const requiredTechniques = useMemo(
    () => (executedQuery && executedQuery === example?.query
      ? example.expected_techniques
      : []),
    [example, executedQuery],
  );
  const channels = useMemo(
    () =>
      response ? readChannels(response, requiredTechniques, readiness) : [],
    [readiness, requiredTechniques, response],
  );
  const reasonScenario = useMemo(
    () => mosaicRetrievalExamples.find((candidate) => candidate.stage === "reason"),
    [],
  );

  const selectExample = (id: string) => {
    const index = mosaicRetrievalExamples.findIndex((candidate) => candidate.id === id);
    if (index < 0) return;
    requestVersion.current += 1;
    setSelected(index);
    setQuery(mosaicRetrievalExamples[index].query);
    setCarriedOver(false);
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
    setCarriedOver(false);
    setResponse(null);
    setFirstResponse(null);
    setExecutedQuery("");
    setRunCount(0);
    setError("");
    setLoading(false);
  };

  const run = useCallback(async function run() {
    const requestedQuery = query.trim();
    if (!example || !requestedQuery) return;
    // The gates Shop applied while the hand-off holds, the scenario's own gates
    // once it is over.
    const requestedFilters = carriedOver ? forwardedFilters : example.filters;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setError("");
    try {
      const nextResponse = await api.search(
        requestedQuery,
        requestedFilters,
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
  }, [carriedOver, example, forwardedFilters, query]);

  /**
   * Run the forwarded query on arrival, once.
   *
   * Landing on an empty Retrieve stage after following "See how this was retrieved"
   * makes the hand-off read as three separate demonstrations rather than one request
   * travelling through the product. `ranForwarded` gates it so editing the query and
   * re-rendering does not re-fire it.
   */
  useEffect(() => {
    if (!forwardedQuery || ranForwarded.current || !example) return;
    ranForwarded.current = true;
    void run();
  }, [example, forwardedQuery, run]);

  const counts = response?.diagnostics?.candidate_counts;
  const profile = response?.diagnostics?.retrieval_profile;
  const gates = response ? appliedGates(response) : [];

  // The same wrapper and masthead the other two Playground lenses use.
  return (
    <div className="page mosaic-labs-page labs-premium lab-page">
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
        deck={RETRIEVAL_SURFACE.headline}
        title={RETRIEVAL_SURFACE.title}
      />

      {/* The bridge, above the three stages: the words Shop uses on the left, the
          PostgreSQL feature that produced them on the right. It is the whole
          reason this surface exists, so it is not behind a disclosure. */}
      <section className="labs-bridge" aria-labelledby="labs-bridge-title">
        <h2 id="labs-bridge-title">What Shop calls it, and what Aurora runs</h2>
        <dl>
          {armLanguage.map((arm) => (
            <div key={arm.key}>
              <dt>{arm.label}</dt>
              <dd><code>{arm.mechanism}</code></dd>
            </div>
          ))}
        </dl>
        <p>
          One query, three candidate sets, fused into one order and then reranked.
          Every number on this page is a value the run reported.
        </p>
      </section>

      {/* One request travelling through the product, said out loud. Without this the
          Playground reads as a third separate demonstration that happens to hold
          the same words. */}
      {carriedOver && forwardedQuery ? (
        <p className="labs-carried-over">
          <ArrowRightLeft aria-hidden="true" size={15} />
          <span>
            Carried over from Shop:{" "}
            <code>{forwardedQuery}</code>
          </span>
          <small>
            {Object.keys(forwardedFilters).length
              ? `Same query, same ${Object.keys(forwardedFilters).length} eligibility gate${
                Object.keys(forwardedFilters).length === 1 ? "" : "s"
              }.`
              : "Same query, no eligibility gates, as on Shop."}
          </small>
        </p>
      ) : null}

      {/* No progress rail here any more. It drew Retrieve / Rank / Reason as three
          numbered steps directly above the three numbered stages below, which is
          the same information architecture twice on one screen. It stays on
          /search, which has no stages of its own. */}
      {outcome ? <LabOutcomeBanner outcome={outcome} /> : null}

      <PlaygroundStage
        number="01"
        title="Retrieve"
        summary="What was asked, what was eligible, and which of the three arms found anything."
        stale={loading && Boolean(response)}
      >
        {response && counts && profile ? (
          <>
            <RetrievalChannelMap readings={channels} />

            <PlaygroundFigures label="Retrieval figures">
              <PlaygroundFigure
                label="Query as sent"
                value={<code className="labs-query-echo">{response.query}</code>}
                detail={
                  response.normalized_query
                  && response.normalized_query !== response.query
                    ? `normalized to "${response.normalized_query}"`
                    : "sent verbatim, no rewriting"
                }
              />
              <PlaygroundFigure
                label="Eligibility gates"
                value={gates.length}
                detail={gates.length ? gates.join(" · ") : "no catalog gates applied"}
              />
              <PlaygroundFigure
                label="Candidate pool"
                value={counts.fused_pool ?? 0}
                detail={`bounded at ${profile.fused_limit} by the retrieval profile`}
              />
              <PlaygroundFigure
                label="Rows returned"
                value={response.results.length}
                detail={`top-k requested: ${profile.result_limit}`}
              />
            </PlaygroundFigures>

            <RetrievalDiagnosticsStrip response={response} />

            <PlaygroundDisclosureShelf>
              <PlaygroundDisclosure
                label="View candidate rows"
                hint={`${response.results.length} returned rows, every arm rank`}
              >
                <CandidateRows products={response.results} />
              </PlaygroundDisclosure>
              <PlaygroundDisclosure
                label="View retrieval profile"
                hint="the bounds this run was given"
              >
                <dl className="labs-profile">
                  {Object.entries(profile).map(([name, value]) => (
                    <div key={name}>
                      <dt>{name.replaceAll("_", " ")}</dt>
                      <dd className="mono">{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </PlaygroundDisclosure>
            </PlaygroundDisclosureShelf>
          </>
        ) : loading ? (
          <p className="labs-stage-awaiting" role="status">
            Embedding the query and running all three arms.
          </p>
        ) : (
          <PlaygroundDormant
            steps={[
              ...armLanguage.map((arm) => arm.label),
              "Eligibility gates",
              "Bounded candidate pool",
            ]}
            hint="Run the pipeline to fill each step with the count it reported."
          />
        )}
      </PlaygroundStage>

      <PlaygroundStage
        number="02"
        title="Rank"
        summary="Each arm's own rank, what it contributed to the combined score, and what reranking then changed."
        stale={loading && Boolean(response)}
      >
        <RetrievalObservatory
          example={example}
          loading={loading}
          response={response}
        />

        {response ? (
          <>
            <SearchRetrievalReceipt response={response} />
            <PlaygroundDisclosureShelf>
              <PlaygroundDisclosure
                label="View RRF math"
                hint="1 / (k + rank), per arm, summed"
              >
                <RrfMath response={response} />
              </PlaygroundDisclosure>
              <PlaygroundDisclosure
                label="View fusion defect"
                hint="Lab 2: expected vs. broken contribution, per arm"
              >
                <FusionDefectLens response={response} />
              </PlaygroundDisclosure>
              <PersistedRunDisclosures response={response} />
            </PlaygroundDisclosureShelf>
          </>
        ) : null}

        {firstResponse && response && runCount > 1 ? (
          <section className="retrieval-run-comparison" aria-labelledby="retrieval-run-comparison-title">
            <header>
              <div>
                <h3 id="retrieval-run-comparison-title">First run and latest run</h3>
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
      </PlaygroundStage>

      {/* Not a numbered stage: this reads two persisted events Stage 01/02 already
          produced rather than running its own retrieval, so it sits between them
          and Reason as a lens over that evidence, not a fourth pipeline step. */}
      <RepairEvidence latestSearchEventId={response?.search_event_id ?? null} />

      <PlaygroundStage
        number="03"
        title="Reason"
        summary="What the agent retrieved, what the application registered and authorized, and which citations resolve."
      >
        {reasonScenario ? (
          <ReasonStage
            question={reasonScenario.query}
            filters={reasonScenario.filters as SearchFilters}
          />
        ) : null}
      </PlaygroundStage>

      <PlaygroundStage
        number="04"
        title="Prove"
        summary="Did we fix the scenarios without weakening the system? The Retrieval Scorecard, from the canonical evaluation artifact."
      >
        <RetrievalScorecard />
        <PackageFinale />
      </PlaygroundStage>
    </div>
  );
}
