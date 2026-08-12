import {
  ChevronRight,
  CircleCheck,
  FileText,
  GitCompareArrows,
  LoaderCircle,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect } from "react";
import Markdown from "react-markdown";
import { formatPrice } from "../format";
import { productImage } from "../media";
import type { AgentResponse } from "../types";
import { SearchComposer } from "./SearchComposer";

type AssistStage = "understand" | "retrieve" | "rank" | "answer";

const stages: Array<{ id: AssistStage; label: string }> = [
  { id: "understand", label: "Interpret" },
  { id: "retrieve", label: "Retrieve" },
  { id: "rank", label: "Compare" },
  { id: "answer", label: "Cite" },
];

interface AskMosaicProps {
  open: boolean;
  query: string;
  loading: boolean;
  activeStage: AssistStage | null;
  activeStageDetail: string;
  streamedAnswer: string;
  error: string;
  response: AgentResponse | null;
  onClose: () => void;
  onRun: (query: string) => void;
  onHighlight: (productId: number | null) => void;
}

export function AskMosaic({
  open,
  query,
  loading,
  activeStage,
  activeStageDetail,
  streamedAnswer,
  error,
  response,
  onClose,
  onRun,
  onHighlight,
}: AskMosaicProps) {
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="shop-agent-layer">
      <button
        className="shop-agent-backdrop"
        type="button"
        aria-label="Close Ask Mosaic"
        onClick={onClose}
      />
      <aside
        className="shop-agent-drawer"
        role="dialog"
        aria-labelledby="shop-agent-title"
      >
        <header>
          <div className="shop-agent-brand">
            <span><Sparkles size={18} /></span>
            <div>
              <p className="eyebrow">Contextual product intelligence</p>
              <h2 id="shop-agent-title">Ask Mosaic</h2>
            </div>
          </div>
          <button type="button" aria-label="Close Ask Mosaic" onClick={onClose}>
            <X size={20} />
          </button>
        </header>

        <div className="shop-agent-body">
          <div className="shop-agent-composer">
            <SearchComposer
              compact
              initialValue={query}
              inputLabel="Ask Mosaic request"
              pending={loading}
              submitLabel="Ask"
              placeholder="Describe the decision, constraints, and trade-offs"
              onSubmit={onRun}
            />
          </div>

          {loading || activeStage ? (
            <ol className="shop-agent-progress" aria-label="Ask Mosaic activity">
              {stages.map((stage, index) => {
                const activeIndex = activeStage
                  ? stages.findIndex((item) => item.id === activeStage)
                  : stages.length;
                const state = index < activeIndex
                  ? "complete"
                  : index === activeIndex
                    ? "active"
                    : "";
                return (
                  <li className={state} key={stage.id}>
                    <span>
                      {state === "complete"
                        ? <CircleCheck size={13} />
                        : state === "active"
                          ? <LoaderCircle className="spin" size={13} />
                          : index + 1}
                    </span>
                    {stage.label}
                  </li>
                );
              })}
            </ol>
          ) : null}

          {loading && activeStage ? (
            <section className="shop-agent-live-status" role="status">
              <LoaderCircle className="spin" size={20} />
              <div>
                <small>Working now</small>
                <strong>{stages.find((stage) => stage.id === activeStage)?.label}</strong>
                <p>{activeStageDetail}</p>
              </div>
            </section>
          ) : null}

          {error ? <p className="shop-agent-error" role="alert">{error}</p> : null}

          {!loading && !error && !response ? (
            <section className="shop-agent-empty">
              <GitCompareArrows size={24} />
              <h3>Product decision</h3>
              <p>State the constraints, alternatives, and trade-off you need resolved.</p>
            </section>
          ) : null}

          {response ? (
            <>
              <section className="shop-agent-answer">
                <p className="eyebrow"><Sparkles size={13} /> Recommendation</p>
                <Markdown>{streamedAnswer || response.answer}</Markdown>
              </section>

              <section className="shop-agent-section">
                <header>
                  <GitCompareArrows size={17} />
                  <h3>Compared shortlist</h3>
                </header>
                <ol className="shop-agent-shortlist">
                  {response.recommendations.slice(0, 4).map((product, index) => (
                    <li
                      key={product.product_id}
                      tabIndex={0}
                      onFocus={() => onHighlight(product.product_id)}
                      onBlur={() => onHighlight(null)}
                      onMouseEnter={() => onHighlight(product.product_id)}
                      onMouseLeave={() => onHighlight(null)}
                    >
                      <span>{index + 1}</span>
                      <img
                        src={productImage(product)}
                        alt=""
                        width={1200}
                        height={800}
                        loading="lazy"
                        decoding="async"
                      />
                      <div>
                        <strong>{product.model}</strong>
                        <small>
                          {product.brand} · {formatPrice(product.price_cents, product.currency)}
                        </small>
                        <em>
                          {index === 0 ? "Best overall · " : ""}
                          {product.signals
                            ? `RRF #${product.signals.pre_rerank_rank} · Final #${product.signals.final_rank}`
                            : "Retrieved shortlist"}
                        </em>
                      </div>
                      <ChevronRight size={16} />
                    </li>
                  ))}
                </ol>
              </section>

              {response.recommendations[0]?.signals ? (
                <details className="shop-agent-ranking">
                  <summary>Why this ranked first</summary>
                  <dl>
                    <div>
                      <dt>FTS rank</dt>
                      <dd>{response.recommendations[0].signals?.fts.rank ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>pg_trgm rank</dt>
                      <dd>{response.recommendations[0].signals?.trigram.rank ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Vector rank</dt>
                      <dd>{response.recommendations[0].signals?.semantic.rank ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>RRF rank</dt>
                      <dd>{response.recommendations[0].signals?.pre_rerank_rank ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Reranker</dt>
                      <dd>{response.recommendations[0].signals?.rerank_score?.toFixed(3) ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Final rank</dt>
                      <dd>{response.recommendations[0].signals?.final_rank ?? "-"}</dd>
                    </div>
                  </dl>
                </details>
              ) : null}

              <section className="shop-agent-section">
                <header>
                  <FileText size={17} />
                  <h3>Evidence</h3>
                </header>
                <ol className="shop-agent-evidence">
                  {response.citations.map((citation) => (
                    <li key={`${citation.number}-${citation.evidence_id}`}>
                      <span>[{citation.number}]</span>
                      <div>
                        <strong>{citation.title}</strong>
                        <p>{citation.quote}</p>
                        <small>
                          Evidence #{citation.evidence_id} · {citation.evidence_type} · {citation.revision}
                        </small>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>

              <section className="shop-agent-section">
                <header>
                  <CircleCheck size={17} />
                  <h3>Activity</h3>
                </header>
                <ol className="shop-agent-activity">
                  {response.trace.map((step) => (
                    <li className={step.outcome} key={step.sequence}>
                      <span>{step.sequence}</span>
                      <div>
                        <strong>{step.tool}</strong>
                        <small>{step.detail}</small>
                        {Object.keys(step.arguments).length ? (
                          <code>{JSON.stringify(step.arguments)}</code>
                        ) : null}
                        {step.retrieval_run_id ? (
                          <em>Run {step.retrieval_run_id.slice(0, 8)}</em>
                        ) : null}
                        {step.latency_ms != null ? (
                          <em>{Math.round(step.latency_ms)} ms</em>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>

              {response.recommendations.length >= 2 ? (
                <div className="shop-agent-followups" aria-label="Ask Mosaic follow-up actions">
                  <button
                    type="button"
                    onClick={() => onRun(
                      `Compare ${response.recommendations[0].model} with ${response.recommendations[1].model} and explain the decisive trade-offs.`,
                    )}
                  >
                    Compare top two
                  </button>
                  <button
                    type="button"
                    onClick={() => onRun(
                      `Explain why ${response.recommendations[0].model} ranked first using retrieval and evidence signals.`,
                    )}
                  >
                    Explain ranking
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
