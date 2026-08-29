import {
  ArrowRight,
  Bot,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  Database,
  GitCompareArrows,
  Search as SearchIcon,
  Sparkles,
  Star,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import { Link } from "wouter";
import { api } from "../api";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { ProductCard } from "../components/ProductCard";
import { SearchComposer } from "../components/SearchComposer";
import { CatalogLoadingState, ErrorState } from "../components/States";
import { WorkshopProgress } from "../components/WorkshopProgress";
import { formatAvailability, formatPrice, isPurchasable } from "../format";
import { fusionLabel } from "../fusion";
import { agentLabOutcome } from "../labOutcome";
import { mosaicRetrievalExamples } from "../labMissions";
import { productImage, productImageMap } from "../media";
import { useSearchParams } from "../navigation";
import type {
  AgentResponse,
  Domain,
  ProductSummary,
  SearchFilters,
  SearchResponse,
} from "../types";

type Mode = "retrieval" | "agent";
type AgentActivityId = "understand" | "retrieve" | "rank" | "answer";
type AgentActivityStatus = "pending" | "active" | "complete";

function filtersFromParams(params: URLSearchParams): SearchFilters {
  const serialized = params.get("filters");
  if (serialized) {
    try {
      const parsed = JSON.parse(serialized);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as SearchFilters;
      }
    } catch {
      // A hand-edited URL falls back to its readable domain parameter.
    }
  }
  const domain = params.get("domain");
  return domain ? { domain: domain as Domain } : {};
}

const agentActivitySteps: Array<{
  id: AgentActivityId;
  title: string;
  detail: string;
}> = [
  {
    id: "understand",
    title: "Interpret request",
    detail: "Separating preferences from hard constraints.",
  },
  {
    id: "retrieve",
    title: "Retrieve evidence",
    detail: "Gathering bounded catalog evidence.",
  },
  {
    id: "rank",
    title: "Compare ranks",
    detail: "Checking eligibility and source provenance.",
  },
  {
    id: "answer",
    title: "Compose cited answer",
    detail: "Delivering only source-backed claims.",
  },
];

function initialAgentActivity() {
  return agentActivitySteps.map((step) => ({
    ...step,
    status: "pending" as AgentActivityStatus,
  }));
}

/** Entry points for the empty state, phrased to show what each mode is for. */
const starterQueries: Array<{ query: string; mode: Mode; note: string }> = [
  {
    query: "noise cancelling over-ear headphones for focused work",
    mode: "retrieval",
    note: "Lexical and semantic arms on one query",
  },
  {
    query: "ergonomic task chair with adjustable lumbar support",
    mode: "retrieval",
    note: "Attribute terms the lexical arm can match exactly",
  },
  {
    query: "What should I buy for a quiet home office under $600?",
    mode: "agent",
    note: "Decomposed into several retrievals, then cited",
  },
  {
    query: "Compare running shoes for daily training",
    mode: "agent",
    note: "Gathers evidence across products before answering",
  },
];

const followUpPrompts = [
  "Which has the strongest customer rating?",
  "Compare the top three on price",
  "Which is best for daily use?",
  "Show only in-stock options",
];

function collectionLabels(products: ProductSummary[], product: ProductSummary, index: number) {
  const labels: string[] = [];
  const prices = products.map((item) => item.price_cents);
  const ratedProducts = products.filter((item) => item.rating !== null && item.review_count > 0);
  const lowestPrice = prices.length ? Math.min(...prices) : null;
  const highestRating = ratedProducts.length
    ? Math.max(...ratedProducts.map((item) => item.rating ?? 0))
    : null;

  if (index === 0) labels.push("Best overall");
  if (highestRating !== null && product.rating === highestRating) labels.push("Top rated");
  if (lowestPrice !== null && product.price_cents === lowestPrice) labels.push("Best value");
  if (isPurchasable(product.availability)) labels.push("Ready to ship");

  return labels.slice(0, 2);
}

function topPickReasons(
  product: ProductSummary,
  mode: Mode,
  diagnostics: SearchResponse["diagnostics"] | undefined,
) {
  const reasons = [
    {
      title: mode === "agent" ? "Included in the shortlist" : "Top retrieval result",
      detail: mode === "agent"
        ? "The assistant selected this product from the catalog evidence it gathered."
        : "This product ranked first in the current hybrid retrieval result set.",
    },
    {
      title: isPurchasable(product.availability) ? "Ready to order" : "Availability",
      detail: formatAvailability(product.availability),
    },
  ];

  if (product.rating !== null && product.review_count > 0) {
    reasons.push({
      title: "Customer signal",
      detail: `${product.rating.toFixed(1)} from ${product.review_count.toLocaleString()} catalog reviews`,
    });
  }

  if (diagnostics) {
    reasons.push({
      title: "Hybrid evidence",
      detail: `${diagnostics.strategy} retrieval with ${diagnostics.rerank_status} reranking`,
    });
  }

  return reasons.slice(0, 4);
}

export function structuredAnswer(answer: string) {
  return answer.replace(
    /^(Summary|Recommendations|Trade-offs)\s*:?\s*$/gm,
    "## $1",
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const paramsKey = params.toString();
  const query = params.get("q") ?? "";
  const mode: Mode = params.get("mode") === "agent" ? "agent" : "retrieval";
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [traceOpen, setTraceOpen] = useState(false);
  const [agentStreaming, setAgentStreaming] = useState(false);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [agentActivity, setAgentActivity] = useState(initialAgentActivity);
  const [comparisonIds, setComparisonIds] = useState<number[]>([]);
  const requestVersion = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const filters = useMemo(
    () => filtersFromParams(new URLSearchParams(paramsKey)),
    [paramsKey],
  );
  const labMission = useMemo(
    () => mosaicRetrievalExamples.find(
      (mission) => (
        mission.id === new URLSearchParams(paramsKey).get("mission")
        && mission.stage === "reason"
      ),
    ),
    [paramsKey],
  );

  const activateAgentStage = useCallback((
    activeId: AgentActivityId,
    complete = false,
  ) => {
    const activeIndex = agentActivitySteps.findIndex((step) => step.id === activeId);
    setAgentActivity(
      agentActivitySteps.map((step, index) => ({
        ...step,
        status: (
          complete || index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending"
        ) as AgentActivityStatus,
      })),
    );
  }, []);

  const execute = useCallback(
    async (nextQuery: string, nextMode = mode) => {
      requestController.current?.abort();
      const controller = new AbortController();
      requestController.current = controller;
      const version = requestVersion.current + 1;
      requestVersion.current = version;
      setLoading(true);
      setError("");
      setSearch(null);
      setAgent(null);
      setAgentStreaming(false);
      setStreamedAnswer("");
      setTraceOpen(false);
      setComparisonIds([]);
      try {
        if (nextMode === "agent") {
          setAgentStreaming(true);
          setAgentActivity(initialAgentActivity());
          await api.agentStream(nextQuery, filters, (event) => {
            if (version !== requestVersion.current) return;
            if (event.type === "stage") {
              activateAgentStage(event.id);
            } else if (event.type === "answer_start") {
              setAgent(event.response);
              setComparisonIds(
                event.response.recommendations
                  .slice(0, 4)
                  .map((product) => product.product_id),
              );
              setLoading(false);
            } else if (event.type === "answer_delta") {
              setStreamedAnswer((answer) => answer + event.delta);
            } else if (event.type === "complete") {
              setAgent(event.response);
              setStreamedAnswer(event.response.answer);
              setAgentStreaming(false);
              activateAgentStage("answer", true);
            }
            // `partial` carries mid-run retrieval for the Ask Mosaic rail. This
            // surface renders the finished response only.
          }, undefined, { signal: controller.signal });
        } else {
          const response = await api.search(nextQuery, filters, {
            signal: controller.signal,
          });
          if (version !== requestVersion.current) return;
          setSearch(response);
          setComparisonIds(
            response.results.slice(0, 4).map((product) => product.product_id),
          );
        }
      } catch (cause) {
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setError(cause instanceof Error ? cause.message : "Search failed");
        setAgentStreaming(false);
      } finally {
        if (version === requestVersion.current) {
          setLoading(false);
          if (requestController.current === controller) {
            requestController.current = null;
          }
        }
      }
    },
    [activateAgentStage, filters, mode],
  );

  useEffect(() => {
    if (query) {
      void execute(query, mode);
    } else {
      requestController.current?.abort();
      requestController.current = null;
      requestVersion.current += 1;
      setLoading(false);
      setError("");
      setSearch(null);
      setAgent(null);
      setAgentStreaming(false);
      setStreamedAnswer("");
      setTraceOpen(false);
      setComparisonIds([]);
    }
    return () => requestController.current?.abort();
  }, [execute, mode, query]);

  const run = useCallback(
    (nextQuery: string, nextMode = mode) => {
      const nextParams = new URLSearchParams(params);
      nextParams.set("q", nextQuery);
      nextParams.set("mode", nextMode);
      if (labMission && nextQuery !== labMission.query) {
        nextParams.delete("mission");
      }
      if (nextParams.toString() === paramsKey) {
        void execute(nextQuery, nextMode);
        return;
      }
      setParams(nextParams);
    },
    [execute, labMission, mode, params, paramsKey, setParams],
  );

  function changeMode(nextMode: Mode) {
    if (nextMode === mode) return;
    if (query) {
      run(query, nextMode);
      return;
    }
    const nextParams = new URLSearchParams(params);
    nextParams.set("mode", nextMode);
    setParams(nextParams);
  }

  const products = agent?.recommendations ?? search?.results ?? [];
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const gridImages = productImageMap(products);
  const diagnostics = search?.diagnostics;
  const comparisonProducts = comparisonIds
    .map((productId) => products.find((product) => product.product_id === productId))
    .filter((product): product is ProductSummary => Boolean(product));
  const topPick = products[0];
  const topPickReasonsList = topPick ? topPickReasons(topPick, mode, diagnostics) : [];
  const labOutcome = labMission && (agent || error)
    ? agentLabOutcome(labMission, agent, error)
    : null;
  const comparisonAttributes = Array.from(
    new Set(
      comparisonProducts.flatMap((product) =>
        Object.keys(product.attributes).filter((key) => {
          const value = product.attributes[key];
          return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
        }),
      ),
    ),
  ).slice(0, 4);

  function followUp(nextQuery: string) {
    run(nextQuery, "agent");
  }

  function updateComparison(productId: number, checked: boolean) {
    setComparisonIds((current) => {
      if (!checked) return current.filter((id) => id !== productId);
      if (current.includes(productId) || current.length >= 4) return current;
      return [...current, productId];
    });
  }

  return (
    <div className="page search-page">
      <header className="search-page-header">
        <SearchComposer
          initialValue={query}
          pending={loading || agentStreaming}
          onSubmit={(value) => void run(value)}
        />
        <div className="mode-control" aria-label="Search mode">
          <button
            type="button"
            className={mode === "retrieval" ? "active" : ""}
            aria-pressed={mode === "retrieval"}
            disabled={loading || agentStreaming}
            onClick={() => changeMode("retrieval")}
          >
            <SearchIcon size={16} /> Retrieval
          </button>
          <button
            type="button"
            className={mode === "agent" ? "active" : ""}
            aria-pressed={mode === "agent"}
            disabled={loading || agentStreaming}
            onClick={() => changeMode("agent")}
          >
            <Bot size={16} /> Agent
          </button>
        </div>
      </header>

      <WorkshopProgress active={mode === "agent" ? "reason" : "retrieve"} />

      {labOutcome ? <LabOutcomeBanner outcome={labOutcome} /> : null}

      {!query && !loading ? (
        <section className="search-empty">
          <Sparkles size={28} />
          <h1>Search the Shop</h1>
          <p>
            Begin with a product need or ask Mosaic to assemble a collection
            from catalog evidence.
          </p>
          {/* The page was blank on arrival with nothing to act on. These are
              real queries against the loaded catalog, not decoration. */}
          <div className="search-starters">
            {starterQueries.map((starter) => (
              <button
                key={starter.query}
                type="button"
                onClick={() => void run(starter.query, starter.mode)}
              >
                <strong>{starter.query}</strong>
                <small>
                  {starter.mode === "agent" ? "Agent" : "Retrieval"} · {starter.note}
                </small>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {mode === "agent" && (loading || agentStreaming) ? (
        <section className="agent-progress-surface" aria-live="polite">
          <header>
            <span className="agent-thinking-dot" aria-hidden="true" />
            <div>
              <p className="eyebrow">Mosaic Agent</p>
              <h2>{agentStreaming ? "Building a cited response" : "Gathering catalog evidence"}</h2>
            </div>
            <span className="agent-progress-live">Live</span>
          </header>
          <ol>
            {agentActivity.map((step) => (
              <li key={step.id} className={step.status}>
                <span aria-hidden="true" />
                <div>
                  <strong>{step.title}</strong>
                  <small>{step.detail}</small>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {/* A centered spinner collapsed the results column on every rerun, so the
          page bounced between layouts. The heading plus the shared skeleton
          keeps the grid footprint stable while retrieval runs. */}
      {loading && mode !== "agent" ? (
        <>
          <section className="search-result-heading" aria-live="polite">
            <p className="eyebrow">Mosaic Shop</p>
            <h1>Searching for “{query}”</h1>
            <p>Running hybrid retrieval across the catalog.</p>
          </section>
          <CatalogLoadingState />
        </>
      ) : null}
      {error ? (
        <ErrorState message={error} onRetry={() => void execute(query, mode)} />
      ) : null}

      {!loading && !error && (search || agent) ? (
        <>
          <section className="search-result-heading">
            <p className="eyebrow">Mosaic Shop</p>
            <h1>Results for “{query}”</h1>
            <p>
              {products.length} products match this request
              {agent ? " after the agent gathered and compared catalog evidence." : "."}
            </p>
          </section>

          <div className="search-filter-row">
            <span><SearchIcon size={15} /> Current request</span>
            {Object.entries(search?.applied_filters ?? filters).map(([key, value]) => (
              <span className="filter-chip" key={key}>
                {key.replaceAll("_", " ")}: {String(value)}
              </span>
            ))}
            {diagnostics ? (
              <span className="filter-chip">
                {diagnostics.candidate_counts.fused_pool} fused candidates
              </span>
            ) : null}
          </div>

          <div className="search-workspace">
            <section className="answer-column">
              {products.length ? (
                <div className="search-product-grid">
                  {products.map((product, index) => (
                    <div id={`product-${product.product_id}`} key={product.product_id}>
                      <ProductCard
                        product={product}
                        imageSrc={gridImages.get(product.product_id)}
                        showSignals
                        showCompare
                        compareChecked={comparisonIds.includes(product.product_id)}
                        compareDisabled={
                          comparisonIds.length >= 4
                          && !comparisonIds.includes(product.product_id)
                        }
                        onCompareChange={updateComparison}
                        collectionLabels={collectionLabels(products, product, index)}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <section className="search-empty" role="status">
                  <SearchIcon size={24} aria-hidden="true" />
                  <h2>No products matched this request</h2>
                  <p>Adjust the wording or remove a filter, then run the search again.</p>
                </section>
              )}

              {comparisonProducts.length > 1 ? (
                <section className="comparison-panel">
                  <div className="comparison-heading">
                    <GitCompareArrows size={19} />
                    <div>
                      <h2>Compare key details</h2>
                      <p>Source fields from the selected products.</p>
                    </div>
                  </div>
                  <div className="comparison-table-wrap">
                    <table className="comparison-table">
                      <thead>
                        <tr>
                          <th>Attribute</th>
                          {comparisonProducts.map((product) => (
                            <th key={product.product_id}>
                              <span>{product.brand}</span>
                              {product.model}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <th>Price</th>
                          {comparisonProducts.map((product) => (
                            <td key={product.product_id}>{formatPrice(product.price_cents, product.currency)}</td>
                          ))}
                        </tr>
                        <tr>
                          <th>Rating</th>
                          {comparisonProducts.map((product) => (
                            <td key={product.product_id}>
                              {product.rating !== null ? (
                                <><Star size={13} fill="currentColor" /> {product.rating.toFixed(1)}</>
                              ) : "Not rated"}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <th>Availability</th>
                          {comparisonProducts.map((product) => (
                            <td key={product.product_id}>{formatAvailability(product.availability)}</td>
                          ))}
                        </tr>
                        {comparisonAttributes.map((attribute) => (
                          <tr key={attribute}>
                            <th>{attribute.replaceAll("_", " ")}</th>
                            {comparisonProducts.map((product) => {
                              const value = product.attributes[attribute];
                              return (
                                <td key={product.product_id}>
                                  {value === undefined
                                    ? "-"
                                    : typeof value === "boolean"
                                      ? value ? "Yes" : "No"
                                      : String(value)}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
            </section>

            <aside className="insights-panel">
              <div className="assistant-title">
                <Sparkles size={21} />
                <div>
                  <strong>Mosaic Collection Assistant</strong>
                  <small>{agent ? "Cited shortlist" : "Why this collection matches"}</small>
                </div>
              </div>
              {topPick ? (
                <section className="collection-match-panel">
                  <p className="eyebrow">Why it matched</p>
                  <ul>
                    {topPickReasonsList.map((reason) => (
                      <li key={reason.title}>
                        <CircleCheck size={16} />
                        <span>
                          <strong>{reason.title}</strong>
                          <small>{reason.detail}</small>
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {agent ? (
                <>
                  <div className={agentStreaming ? "agent-answer streaming" : "agent-answer"}>
                    {agentStreaming ? (
                      <p className="agent-streamed-copy">
                        {streamedAnswer}
                        <span className="agent-stream-cursor" aria-hidden="true" />
                      </p>
                    ) : (
                      <Markdown>{structuredAnswer(agent.answer)}</Markdown>
                    )}
                  </div>
                  {agent.citations.length ? (
                    <div className="citation-list">
                      <h2>Sources</h2>
                      {agent.citations.map((citation) => (
                        <a key={citation.number} href={`#product-${citation.product_id}`}>
                          <span>[{citation.number}]</span>
                          <strong>{citation.title}</strong>
                          <small>Evidence #{citation.evidence_id} · {citation.evidence_type}</small>
                        </a>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="retrieval-summary">
                  <p>
                    PostgreSQL gathered lexical, fuzzy, and semantic candidates,
                    fused their ranks, then returned this ordered set.
                  </p>
                  <ol className="pipeline-list">
                    <li><CircleCheck size={15} /> Full-text and pg_trgm candidates</li>
                    <li><CircleCheck size={15} /> Cohere Embed v4 semantic candidates</li>
                    <li>
                      <CircleCheck size={15} />
                      {diagnostics ? `${fusionLabel(diagnostics.strategy)}, k=${diagnostics.retrieval_profile.rrf_k}` : fusionLabel()}
                    </li>
                    <li>
                      <CircleCheck size={15} />
                      Cohere Rerank {diagnostics?.rerank_status ?? "unavailable"}
                    </li>
                  </ol>
                </div>
              )}

              {diagnostics ? (
                <section className="diagnostic-summary">
                  <h2>Retrieval diagnostics</h2>
                  <dl className="metric-list">
                    {Object.entries(diagnostics.candidate_counts).map(([key, value]) => (
                      <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>
                    ))}
                    <div><dt>Total latency</dt><dd>{diagnostics.total_latency_ms} ms</dd></div>
                  </dl>
                </section>
              ) : null}

              {agent ? (
                <section className="trace-section">
                  <button className="trace-toggle" type="button" onClick={() => setTraceOpen((value) => !value)}>
                    Agent trace {traceOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  {traceOpen ? (
                    <ol className="agent-trace">
                      {agent.trace.map((step) => (
                        <li className={step.outcome} key={step.sequence}>
                          <span>{step.sequence}</span>
                          <div>
                            <strong>{step.tool}</strong>
                            {step.origin === "controller_fallback" ? (
                              <small>Application controller completion</small>
                            ) : null}
                            <small>{step.detail}</small>
                            {Object.keys(step.arguments).length ? (
                              <code>{JSON.stringify(step.arguments)}</code>
                            ) : null}
                            {step.retrieval_run_id ? (
                              <small className="agent-trace-run">
                                Run {step.retrieval_run_id.slice(0, 8)}
                              </small>
                            ) : null}
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </section>
              ) : null}

              {topPick ? (
                <section className="collection-top-pick">
                  <header>
                    <Sparkles size={16} />
                    <span>Top pick</span>
                  </header>
                  <img src={gridImages.get(topPick.product_id) ?? productImage(topPick)} alt="" />
                  <div>
                    <span className="collection-top-pick-label">Best overall</span>
                    <h2>{topPick.model}</h2>
                    <p>{topPick.short_description}</p>
                    {topPick.rating !== null && topPick.review_count > 0 ? (
                      <span className="collection-top-pick-rating">
                        <Star size={14} fill="currentColor" />
                        {topPick.rating.toFixed(1)} ({topPick.review_count.toLocaleString()})
                      </span>
                    ) : null}
                    <strong>{formatPrice(topPick.price_cents, topPick.currency)}</strong>
                  </div>
                  <Link href={`/products/${topPick.product_id}`}>
                    View product <ArrowRight size={15} />
                  </Link>
                </section>
              ) : null}
            </aside>
          </div>

          <section className="follow-up-panel">
            <div>
              <p className="eyebrow">Continue the search</p>
              <h2>Ask a follow-up</h2>
            </div>
            <div className="follow-up-prompts">
              {followUpPrompts.map((prompt) => (
                <button type="button" key={prompt} onClick={() => followUp(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <SearchComposer
              compact
              placeholder="Ask the agent to compare, narrow, or explain"
              onSubmit={followUp}
            />
            <p className="assistant-boundary">
              <Database size={14} />
              Answers cite inspectable catalog sources and persisted retrieval runs.
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}
