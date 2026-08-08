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
import { useCallback, useEffect, useState } from "react";
import Markdown from "react-markdown";
import { Link } from "wouter";
import { api } from "../api";
import { ProductCard } from "../components/ProductCard";
import { SearchComposer } from "../components/SearchComposer";
import { ErrorState, LoadingState } from "../components/States";
import { useSearchParams } from "../navigation";
import type {
  AgentResponse,
  Domain,
  SearchFilters,
  SearchResponse,
} from "../types";

type Mode = "retrieval" | "agent";

const followUpPrompts = [
  "Which has the strongest customer rating?",
  "Compare the top three on price",
  "Which is best for daily use?",
  "Show only in-stock options",
];

export function structuredAnswer(answer: string) {
  return answer.replace(
    /^(Summary|Recommendations|Trade-offs)\s*:?\s*$/gm,
    "## $1",
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const initialQuery = params.get("q") ?? "";
  const domain = (params.get("domain") || undefined) as Domain | undefined;
  const [mode, setMode] = useState<Mode>(
    params.get("mode") === "agent" ? "agent" : "retrieval",
  );
  const [query, setQuery] = useState(initialQuery);
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [traceOpen, setTraceOpen] = useState(false);
  const filters: SearchFilters = domain ? { domain } : {};

  const run = useCallback(
    async (nextQuery: string, nextMode = mode) => {
      setQuery(nextQuery);
      setLoading(true);
      setError("");
      setSearch(null);
      setAgent(null);
      const nextParams = new URLSearchParams(params);
      nextParams.set("q", nextQuery);
      nextParams.set("mode", nextMode);
      setParams(nextParams, { replace: true });
      try {
        if (nextMode === "agent") {
          setAgent(await api.agent(nextQuery, filters));
        } else {
          setSearch(await api.search(nextQuery, filters));
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Search failed");
      } finally {
        setLoading(false);
      }
    },
    [domain, mode],
  );

  useEffect(() => {
    if (initialQuery) void run(initialQuery, mode);
    // The initial URL is the only automatic trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function changeMode(nextMode: Mode) {
    setMode(nextMode);
    if (query) void run(query, nextMode);
  }

  const products = agent?.recommendations ?? search?.results ?? [];
  const diagnostics = search?.diagnostics;
  const comparisonProducts = products.slice(0, 4);
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
    setMode("agent");
    void run(nextQuery, "agent");
  }

  return (
    <div className="page search-page">
      <header className="search-page-header">
        <SearchComposer
          initialValue={query}
          pending={loading}
          onSubmit={(value) => void run(value)}
        />
        <div className="mode-control" aria-label="Search mode">
          <button
            type="button"
            className={mode === "retrieval" ? "active" : ""}
            onClick={() => changeMode("retrieval")}
          >
            <SearchIcon size={16} /> Retrieval
          </button>
          <button
            type="button"
            className={mode === "agent" ? "active" : ""}
            onClick={() => changeMode("agent")}
          >
            <Bot size={16} /> Agent
          </button>
        </div>
      </header>

      {!query && !loading ? (
        <section className="search-empty">
          <Sparkles size={28} />
          <h1>Search the catalog or ask the agent</h1>
          <p>
            Retrieval runs one inspectable hybrid query. Agent mode decomposes a
            broader question and returns a citation-validated answer.
          </p>
        </section>
      ) : null}

      {loading ? <LoadingState label={mode === "agent" ? "Agent gathering evidence" : "Running hybrid retrieval"} /> : null}
      {error ? <ErrorState message={error} onRetry={() => void run(query)} /> : null}

      {!loading && !error && (search || agent) ? (
        <>
          <section className="search-result-heading">
            <p className="eyebrow">
              {mode === "agent" ? "Agent-guided product discovery" : "Hybrid retrieval results"}
            </p>
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
              <div className="search-product-grid">
                {products.map((product) => (
                  <div id={`product-${product.product_id}`} key={product.product_id}>
                    <ProductCard product={product} showSignals showCompare />
                  </div>
                ))}
              </div>

              {comparisonProducts.length > 1 ? (
                <section className="comparison-panel">
                  <div className="comparison-heading">
                    <GitCompareArrows size={19} />
                    <div>
                      <h2>Compare key details</h2>
                      <p>Source fields from the top-ranked products.</p>
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
                            <td key={product.product_id}>${product.price_usd.toFixed(2)}</td>
                          ))}
                        </tr>
                        <tr>
                          <th>Rating</th>
                          {comparisonProducts.map((product) => (
                            <td key={product.product_id}>
                              <Star size={13} fill="currentColor" /> {product.rating.toFixed(1)}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <th>Availability</th>
                          {comparisonProducts.map((product) => (
                            <td key={product.product_id}>{product.availability}</td>
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
                  <strong>Mosaic AI Assistant</strong>
                  <small>{agent ? "Cited answer" : "Retrieval explanation"}</small>
                </div>
              </div>
              {agent ? (
                <>
                  <div className="agent-answer">
                    <Markdown>{structuredAnswer(agent.answer)}</Markdown>
                  </div>
                  {agent.citations.length ? (
                    <div className="citation-list">
                      <h2>Sources</h2>
                      {agent.citations.map((citation) => (
                        <a key={citation.number} href={`#product-${citation.product_id}`}>
                          <span>[{citation.number}]</span>
                          <strong>{citation.title}</strong>
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
                    <li><CircleCheck size={15} /> Weighted RRF, k={diagnostics?.rrf_k ?? 60}</li>
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
                        <li key={step.sequence}>
                          <span>{step.sequence}</span>
                          <div><strong>{step.tool}</strong><small>{step.detail}</small></div>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </section>
              ) : null}

              {products[0] ? (
                <section className="top-result">
                  <p className="eyebrow">Top-ranked result</p>
                  <h2>{products[0].title}</h2>
                  <p>{products[0].short_description}</p>
                  <Link href={`/products/${products[0].product_id}`}>
                    View product evidence <ArrowRight size={15} />
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
