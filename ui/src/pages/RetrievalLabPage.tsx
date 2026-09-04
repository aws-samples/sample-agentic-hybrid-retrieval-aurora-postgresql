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
  forwardedSearchEvent,
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

/** Enough of a `search_event_id` to recognise on screen, without printing 36 characters. */
function shortEventId(searchEventId: string): string {
  return searchEventId.slice(0, 8);
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
  /**
   * The run Shop actually served, when the link carried it.
   *
   * Re-running the query answered a question nobody asked: the participant
   * followed a link from a result set they were already looking at, and the
   * replay minted a second `mosaic.search_event` whose pool could differ. The
   * run behind those results was then unreachable, so no later comparison could
   * anchor on it.
   */
  const forwardedEvent = useMemo(() => forwardedSearchEvent(params), [params]);
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
  /** The Shop run this surface read back, once it has. Null until then, and null
   * for a hand-off that carried only a query. */
  const [carriedRunId, setCarriedRunId] = useState<string | null>(null);
  /** True once a carried event failed to read back and the query was replayed
   * instead, which the banner has to say rather than quietly re-running. */
  const [carriedRunMissing, setCarriedRunMissing] = useState(false);
  /**
   * The run this mission measures its repairs against.
   *
   * Pinned to the first run after a mission is selected, including a run carried
   * over from Shop, because that is the state the participant is about to change.
   * Re-pinnable, and dropped whenever the mission itself changes: a baseline from
   * one scenario's query says nothing about another's.
   */
  const [baselineSearchEventId, setBaselineSearchEventId] = useState<string | null>(null);
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

  /** Everything a run left behind, cleared together. The pinned baseline belongs
   * to the request that produced it, so a new mission or a new query drops it
   * rather than carrying a comparison across two unrelated queries. */
  const resetRunState = () => {
    requestVersion.current += 1;
    setCarriedOver(false);
    setCarriedRunId(null);
    setCarriedRunMissing(false);
    setBaselineSearchEventId(null);
    setResponse(null);
    setFirstResponse(null);
    setExecutedQuery("");
    setRunCount(0);
    setError("");
    setLoading(false);
  };

  const selectExample = (id: string) => {
    const index = mosaicRetrievalExamples.findIndex((candidate) => candidate.id === id);
    if (index < 0) return;
    resetRunState();
    setSelected(index);
    setQuery(mosaicRetrievalExamples[index].query);
  };

  const editQuery = (value: string) => {
    resetRunState();
    setQuery(value);
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
        // The first run of a mission is the state the participant is about to
        // change, so it becomes the baseline without being asked for. Later runs
        // leave it alone: a baseline that moved every run could never show a
        // repair.
        setBaselineSearchEventId((pinned) => pinned ?? nextResponse.search_event_id);
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
   * Take delivery of the forwarded request on arrival, once.
   *
   * A link that carried the run's own id is read back from
   * `mosaic.search_event` and pinned; nothing is re-run, because re-running is
   * what loses the run. A link that carried only the query is replayed, which is
   * all it can support: landing on an empty Retrieve stage would make the
   * hand-off read as three separate demonstrations rather than one request
   * travelling through the product. `ranForwarded` gates both so editing the
   * query and re-rendering does not re-fire them.
   */
  useEffect(() => {
    if (!forwardedQuery || ranForwarded.current || !example) return;
    ranForwarded.current = true;
    if (!forwardedEvent) {
      void run();
      return;
    }
    let active = true;
    void api
      .retrievalEvent(forwardedEvent)
      .then((event) => {
        if (!active) return;
        setCarriedRunId(event.run.search_event_id);
        setBaselineSearchEventId(event.run.search_event_id);
      })
      .catch(() => {
        if (!active) return;
        setCarriedRunMissing(true);
        void run();
      });
    return () => {
      active = false;
    };
  }, [example, forwardedEvent, forwardedQuery, run]);

  const counts = response?.diagnostics?.candidate_counts;
  const profile = response?.diagnostics?.retrieval_profile;
  const gates = response ? appliedGates(response) : [];
  /**
   * The run this surface currently holds evidence for: a pipeline run once there
   * has been one, otherwise the run carried over from Shop. Both are real
   * persisted events, which is why one field can name either.
   */
  const latestSearchEventId = response?.search_event_id ?? carriedRunId;

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
          One query, three product lists. Aurora combines their positions, then
          reranks the shared pool. Every number on this page is a value the run
          reported.
        </p>
      </section>

      {/* One request travelling through the product, said out loud. Without this the
          Playground reads as a third separate demonstration that happens to hold
          the same words. */}
      {carriedOver && forwardedQuery ? (
        <p className="labs-carried-over">
          <ArrowRightLeft aria-hidden="true" size={15} />
          <span>
            <strong>
              {carriedRunId ? "This is the exact run from Shop" : "Carried over from Shop"}
            </strong>{" "}
            <code>{forwardedQuery}</code>
          </span>
          {carriedRunId ? (
            <small>
              Run {shortEventId(carriedRunId)}, read back from Postgres. Nothing was
              re-run, so this is the pool Shop served.
            </small>
          ) : carriedRunMissing ? (
            <small>
              The Shop run could not be found, so the query was run again. This is a
              new run, not the one behind those results.
            </small>
          ) : (
            <small>
              {Object.keys(forwardedFilters).length
                ? `Same query, same ${Object.keys(forwardedFilters).length} eligibility gate${
                  Object.keys(forwardedFilters).length === 1 ? "" : "s"
                }.`
                : "Same query, no eligibility gates, as on Shop."}
            </small>
          )}
        </p>
      ) : null}

      {/* One line of run bookkeeping: which run is on screen, which one this
          mission measures against, and the way to move the second one. */}
      {latestSearchEventId ? (
        <p className="labs-run-summary">
          <span>
            Run on screen <code>{shortEventId(latestSearchEventId)}</code>
          </span>
          <span>
            {baselineSearchEventId
              ? (
                <>
                  Baseline <code>{shortEventId(baselineSearchEventId)}</code>
                </>
              )
              : "No baseline pinned"}
          </span>
          <button
            className="secondary-button"
            disabled={baselineSearchEventId === latestSearchEventId}
            onClick={() => setBaselineSearchEventId(latestSearchEventId)}
            type="button"
          >
            Pin as baseline
          </button>
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
        summary="What the shopper asked, which products were allowed, and what each search method found."
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
                label="View run limits"
                hint="the retrieval profile used for this request"
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
        summary="Where each product appeared in each candidate list, how those lists were combined, and what reranking moved."
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
                label="View how the three rankings combine"
                hint="RRF formula: 1 / (k + rank), summed per method"
              >
                <RrfMath response={response} />
              </PlaygroundDisclosure>
              <PlaygroundDisclosure
                label="View the Lab 2 fusion defect"
                hint="the expected and broken contribution from each method"
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
      <RepairEvidence
        baselineSearchEventId={baselineSearchEventId}
        latestSearchEventId={latestSearchEventId}
      />

      <PlaygroundStage
        number="03"
        title="Reason"
        summary="Which products and evidence the agent received, what the application allowed into the answer, and whether every citation resolves."
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
        summary="Did the fixes improve the scenarios they target without breaking anything that already worked? Measured from the saved evaluation results."
      >
        <RetrievalScorecard />
        <PackageFinale />
      </PlaygroundStage>
    </div>
  );
}
