import {
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  FileText,
  GitCompareArrows,
  LoaderCircle,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import {
  formatAvailability,
  formatCategoryKey,
  formatPrice,
  formatPriceCompact,
} from "../format";
import { domainLabels, productImage } from "../media";
import type { AgentResponse, ResultSignals, SearchFilters } from "../types";
import { SearchComposer } from "./SearchComposer";

export type AssistStage = "understand" | "retrieve" | "rank" | "answer";

/**
 * One exchange: what was asked, and everything the service has streamed back
 * for it so far.
 *
 * The panel used to hold a single response, so every follow-up erased the
 * exchange that prompted it - "Compare top two" threw away the answer that
 * named the two products, and the panel snapped back to a spinner. Turns
 * accumulate instead, which is what makes the follow-ups worth pressing: the
 * comparison lands under the recommendation it came from.
 */
export interface AskMosaicTurn {
  id: number;
  question: string;
  response: AgentResponse | null;
  /** Text delivered so far by `answer_delta`. Empty until the first token. */
  streamed: string;
  stage: AssistStage | null;
  stageDetail: string;
  error: string;
  loading: boolean;
}

const stages: Array<{ id: AssistStage; label: string }> = [
  { id: "understand", label: "Interpret" },
  { id: "retrieve", label: "Retrieve" },
  { id: "rank", label: "Compare" },
  { id: "answer", label: "Cite" },
];

/**
 * Every tool the service registers, from `service/agent_tools.py`.
 *
 * The label is what the tool does in shopping terms, taken from each function's
 * docstring, and the function name stays beside it. A shopper reads the left
 * column and a participant can open that file and read all five in the right
 * one, which is the whole claim of this panel: the agent orchestrates retrieval
 * rather than replacing it.
 *
 * This is also the panel's opening state, and it used to be three invented
 * example questions: one of them asked the agent to explain a ranking before
 * anything had been ranked. The starters below are the eval set instead.
 */
const agentTools = [
  { fn: "search_products", label: "Search the catalog" },
  { fn: "compare_products", label: "Compare options side by side" },
  { fn: "get_product_evidence", label: "Look up specs and reviews" },
  { fn: "explain_retrieval", label: "Replay the ranking signals" },
  { fn: "synthesize_cited_answer", label: "Write the cited recommendation" },
];

const toolLabels = new Map(agentTools.map((tool) => [tool.fn, tool.label]));

/**
 * Which retrieval arm found a row, in the words a shopper used to ask.
 *
 * `RankSignal.rank` is null for an arm that never retrieved the product, so this
 * reports measured arm membership. The reference design put a "96% match" badge
 * on every row; no such number exists in `ResultSignals`, and the reranker score
 * is the one bounded relevance figure the service actually produces.
 */
const armLabels: Array<[keyof Pick<ResultSignals, "fts" | "trigram" | "semantic">, string]> = [
  ["fts", "your exact words"],
  ["trigram", "close spellings"],
  ["semantic", "what you meant"],
];

function matchReason(signals: ResultSignals | null | undefined): string {
  if (!signals) return "In the retrieved shortlist";
  const matched = armLabels
    .filter(([arm]) => signals[arm].rank != null)
    .map(([, label]) => label);
  const found = matched.length
    ? `Found by ${matched.join(" + ")}`
    : "Carried in by rank fusion";
  if (signals.rerank_score == null) return found;
  return `${found} · Rerank ${signals.rerank_score.toFixed(2)}`;
}

/**
 * The constraints one agent search resolved, as chips.
 *
 * `plan[].filters` is the merged `SearchFilters` the service passed to
 * retrieval, so every chip here is a constraint that ran against the catalog -
 * both the ones the request implied and the ones Shop already had active.
 */
function describeFilters(filters: SearchFilters): string[] {
  // A zero price bound or a zero rating is not a constraint, so the falsy
  // numbers `&&` short-circuits to are dropped by the filter below with the rest.
  const chips: Array<string | number | false | undefined> = [
    filters.domain && domainLabels[filters.domain],
    filters.category_key && formatCategoryKey(filters.category_key),
    filters.brand,
    ...(filters.brands ?? []),
    filters.min_price_cents && `Over ${formatPriceCompact(filters.min_price_cents)}`,
    filters.max_price_cents && `Under ${formatPriceCompact(filters.max_price_cents)}`,
    filters.min_rating && `${filters.min_rating}+ stars`,
    filters.availability && formatAvailability(filters.availability),
    filters.in_stock_only && "In stock only",
    filters.include_refurbished && "Refurbished included",
    filters.include_sponsored && "Sponsored included",
    ...Object.entries(filters.attributes ?? {}).map(
      ([name, value]) => `${name.replace(/_/g, " ")} ${String(value)}`,
    ),
  ];
  return chips.filter((chip): chip is string => Boolean(chip));
}

function StageRail({ activeStage }: { activeStage: AssistStage | null }) {
  const activeIndex = activeStage
    ? stages.findIndex((item) => item.id === activeStage)
    : stages.length;
  return (
    <ol className="ask-mosaic-progress" aria-label="Ask Mosaic activity">
      {stages.map((stage, index) => {
        const state = index < activeIndex
          ? "complete"
          : index === activeIndex
            ? "active"
            : "";
        return (
          <li className={state} key={stage.id}>
            <span>
              {state === "complete"
                ? <CircleCheck size={14} />
                : state === "active"
                  ? <LoaderCircle className="spin" size={14} />
                  : index + 1}
            </span>
            {stage.label}
          </li>
        );
      })}
    </ol>
  );
}

interface ShortlistProps {
  response: AgentResponse;
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

function Shortlist({
  response,
  imageByProductId,
  highlightedProductId,
  onHighlight,
  onSelectProduct,
}: ShortlistProps) {
  return (
    <section className="ask-mosaic-section">
      <header>
        <GitCompareArrows size={18} />
        <div>
          <h3>What I would consider</h3>
          <p>Why each one is here. Select a product to locate it in Shop.</p>
        </div>
      </header>
      <ol className="ask-mosaic-shortlist">
        {response.recommendations.slice(0, 4).map((product, index) => (
          <li
            className={highlightedProductId === product.product_id ? "highlighted" : ""}
            key={product.product_id}
          >
            <button
              type="button"
              onClick={() => onSelectProduct(product.product_id)}
              onFocus={() => onHighlight(product.product_id)}
              onBlur={() => onHighlight(null)}
              onMouseEnter={() => onHighlight(product.product_id)}
              onMouseLeave={() => onHighlight(null)}
            >
              <span className="ask-mosaic-shortlist-media">
                <img
                  src={imageByProductId.get(product.product_id) ?? productImage(product)}
                  alt={product.title}
                  width={1200}
                  height={800}
                  loading="lazy"
                  decoding="async"
                />
                <small>{String(index + 1).padStart(2, "0")}</small>
              </span>
              <div>
                {index === 0 ? <span className="ask-mosaic-card-pick">Best match</span> : null}
                <strong>{product.title}</strong>
                <small>
                  {product.model} · {formatPrice(product.price_cents, product.currency)}
                </small>
                <em>
                  {matchReason(product.signals)}
                </em>
              </div>
              <ChevronRight size={17} />
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * The searches behind the shortlist, which the panel used to fetch and then
 * drop on the floor. `plan` holds one entry per search that returned
 * evidence-backed products, so this is how the request became catalog
 * constraints - the honest form of the reference design's "based on your
 * workspace and past views", which describes personalisation this system does
 * not do.
 */
function Searches({ response }: { response: AgentResponse }) {
  return (
    <details className="ask-mosaic-receipt ask-mosaic-search-receipt">
      <summary>
        <Search size={18} />
        How I searched
        <span>{response.plan.length}</span>
      </summary>
      <ol className="ask-mosaic-searches">
        {response.plan.map((step, index) => {
          const chips = describeFilters(step.filters);
          return (
            <li key={`${index}-${step.query}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{step.query}</strong>
                {chips.length ? (
                  <p>
                    {chips.map((chip) => <em key={chip}>{chip}</em>)}
                  </p>
                ) : (
                  <small>No constraints beyond the query</small>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function Ranking({ response }: { response: AgentResponse }) {
  const winner = response.recommendations[0];
  const signals = winner?.signals;
  if (!signals) return null;
  return (
    <details className="ask-mosaic-ranking">
      <summary>
        <span>Why 01 ranked first</span>
        <small>{winner.model}</small>
      </summary>
      <dl>
        <div>
          <dt>FTS</dt>
          <dd>{signals.fts.rank ?? "-"}</dd>
        </div>
        <div>
          <dt>pg_trgm</dt>
          <dd>{signals.trigram.rank ?? "-"}</dd>
        </div>
        <div>
          <dt>Vector</dt>
          <dd>{signals.semantic.rank ?? "-"}</dd>
        </div>
        <div>
          <dt>RRF</dt>
          <dd>{signals.pre_rerank_rank}</dd>
        </div>
        <div>
          <dt>Reranker</dt>
          <dd>
            {signals.rerank_score?.toFixed(3) ?? "-"}
            {signals.rerank_rank ? ` (#${signals.rerank_rank})` : ""}
          </dd>
        </div>
        {signals.exact_sku_match ? (
          <div>
            <dt>Catalog identity</dt>
            <dd>Exact SKU</dd>
          </div>
        ) : null}
        <div>
          <dt>Final</dt>
          <dd>{signals.final_rank}</dd>
        </div>
      </dl>
    </details>
  );
}

function Evidence({ response }: { response: AgentResponse }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <FileText size={17} />
        Evidence
        <span>{response.citations.length}</span>
      </summary>
      <ol className="ask-mosaic-evidence">
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
    </details>
  );
}

/**
 * Closed on every turn, unlike the other two receipts. Expanded, the trace is
 * the longest block in the panel and pushes the answer, the shortlist, and the
 * citations off a laptop screen; the count in the summary is what a reader needs
 * at a glance.
 */
function Activity({ response }: { response: AgentResponse }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <CircleCheck size={17} />
        Activity receipts
        <span>{response.trace.length}</span>
      </summary>
      <ol className="ask-mosaic-activity">
        {response.trace.map((step) => (
          <li className={step.outcome} key={step.sequence}>
            <span>{String(step.sequence).padStart(2, "0")}</span>
            <div>
              <strong>{toolLabels.get(step.tool) ?? step.tool}</strong>
              <code className="ask-mosaic-tool-fn">{step.tool}</code>
              {step.origin === "controller_fallback" ? (
                <small>Completed by the application controller</small>
              ) : null}
              <small>{step.detail}</small>
              {Object.keys(step.arguments).length ? (
                <code>{JSON.stringify(step.arguments)}</code>
              ) : null}
              <p>
                {step.retrieval_run_id ? (
                  <em>Run {step.retrieval_run_id.slice(0, 8)}</em>
                ) : null}
                {step.latency_ms != null ? (
                  <em>{Math.round(step.latency_ms)} ms</em>
                ) : null}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}

/**
 * What to ask next, written from this answer's own products.
 *
 * Every one of these routes to a tool the service registers: a comparison, a
 * ranking replay, and the specification and review records behind the leader.
 */
function FollowUps({
  response,
  onRun,
}: {
  response: AgentResponse;
  onRun: (query: string) => void;
}) {
  const [first, second] = response.recommendations;
  if (!second) return null;
  return (
    <div className="ask-mosaic-followups" aria-label="Ask Mosaic follow-up actions">
      <button
        type="button"
        onClick={() => onRun(
          `Compare ${first.model} with ${second.model} and explain the decisive trade-offs.`,
        )}
      >
        Compare top two
      </button>
      <button
        type="button"
        onClick={() => onRun(
          `Explain why ${first.model} ranked first using retrieval and evidence signals.`,
        )}
      >
        Why this one?
      </button>
      <button
        type="button"
        onClick={() => onRun(`What do the specs and reviews say about ${first.model}?`)}
      >
        What do reviews say?
      </button>
    </div>
  );
}

interface TurnProps {
  turn: AskMosaicTurn;
  isLatest: boolean;
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onRun: (query: string) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

function Turn({
  turn,
  isLatest,
  imageByProductId,
  highlightedProductId,
  onRun,
  onHighlight,
  onSelectProduct,
}: TurnProps) {
  const response = turn.response;
  const stage = stages.find((item) => item.id === turn.stage);
  return (
    <article className="ask-mosaic-turn">
      <div className="ask-mosaic-ask">
        <span>You asked</span>
        <p>{turn.question}</p>
      </div>

      {turn.loading || turn.stage ? <StageRail activeStage={turn.stage} /> : null}

      {turn.loading && stage ? (
        <section className="ask-mosaic-live" role="status">
          <LoaderCircle className="spin" size={20} />
          <div>
            <small>Working now</small>
            <strong>{stage.label}</strong>
            <p>{turn.stageDetail}</p>
          </div>
        </section>
      ) : null}

      {turn.error ? <p className="ask-mosaic-error" role="alert">{turn.error}</p> : null}

      {response ? (
        <>
          {/* `streaming` draws the caret. The text arrives token by token over
              SSE, so the caret marks a live write rather than decorating a
              finished one. */}
          <section
            className={turn.loading ? "ask-mosaic-answer streaming" : "ask-mosaic-answer"}
          >
            <p><Sparkles size={14} /> Recommendation</p>
            <Markdown>{turn.streamed || response.answer}</Markdown>
          </section>

          <Shortlist
            response={response}
            imageByProductId={imageByProductId}
            highlightedProductId={highlightedProductId}
            onHighlight={onHighlight}
            onSelectProduct={onSelectProduct}
          />

          {response.plan.length ? <Searches response={response} /> : null}

          <Ranking response={response} />

          {response.citations.length ? (
            <Evidence response={response} />
          ) : null}

          {response.trace.length ? <Activity response={response} /> : null}

          {isLatest && !turn.loading ? (
            <FollowUps response={response} onRun={onRun} />
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function EntryState({
  starters,
  onRun,
}: {
  starters: string[];
  onRun: (query: string) => void;
}) {
  return (
    <section className="ask-mosaic-empty">
      <h3>Tell me what you need.</h3>
      <p>
        Set the product, budget, and must-haves. Mosaic compares the Aurora
        catalog and cites the evidence behind each recommendation.
      </p>

      {starters.length ? (
        <div className="ask-mosaic-starters">
          <h4>Try asking</h4>
          <ul aria-label="Example questions">
            {starters.map((starter, index) => (
              <li key={starter}>
                <button type="button" onClick={() => onRun(starter)}>
                  <small aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </small>
                  <span>{starter}</span>
                  <ArrowUpRight size={15} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="ask-mosaic-capability">
        <summary>
          <span>
            <strong>What Mosaic can do</strong>
            <small>Five inspectable tools</small>
          </span>
          <ChevronDown size={17} aria-hidden="true" />
        </summary>
        <div>
          <ul className="ask-mosaic-toolset" aria-label="Tools available to the agent">
            {agentTools.map((tool) => (
              <li key={tool.fn}>
                <span>{tool.label}</span>
                <code>{tool.fn}</code>
              </li>
            ))}
          </ul>
          <small>Typed tools only. No free-text SQL.</small>
        </div>
      </details>
    </section>
  );
}

interface AskMosaicProps {
  open: boolean;
  /** What the composer starts with. The Shop query on a cold open. */
  seedQuery: string;
  /** Active Shop filters passed to every agent request. */
  contextFilters: string[];
  /** Oldest exchange first. */
  turns: AskMosaicTurn[];
  pending: boolean;
  /** Questions from the eval set, one per domain. Empty if the fetch failed. */
  starters: string[];
  /** Photographs the Shop grid assigned, so the rail agrees with the cards. */
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onClose: () => void;
  onRun: (query: string) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

export function AskMosaic({
  open,
  seedQuery,
  contextFilters,
  turns,
  pending,
  starters,
  imageByProductId,
  highlightedProductId,
  onClose,
  onRun,
  onHighlight,
  onSelectProduct,
}: AskMosaicProps) {
  const [modal, setModal] = useState(
    () => window.matchMedia?.("(max-width: 1180px)").matches ?? false,
  );
  const layerRef = useRef<HTMLDivElement | null>(null);
  const sidecarRef = useRef<HTMLElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  const latest = turns.length ? turns[turns.length - 1] : null;
  const streamedLength = latest?.streamed.length ?? 0;

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const preference = window.matchMedia?.("(max-width: 1180px)");
    if (!preference) return;
    const updateMode = () => setModal(preference.matches);
    updateMode();
    preference.addEventListener?.("change", updateMode);
    return () => preference.removeEventListener?.("change", updateMode);
  }, []);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    );
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      const restoreTarget = previouslyFocused.current;
      if (restoreTarget?.isConnected) restoreTarget.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open || !modal) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const background = [
      ...Array.from(layerRef.current?.parentElement?.children ?? []).filter(
        (element) => element !== layerRef.current,
      ),
      ...Array.from(document.querySelectorAll(".site-header")),
    ] as HTMLElement[];
    const prior = background.map((element) => ({
      element,
      inert: element.hasAttribute("inert"),
      ariaHidden: element.getAttribute("aria-hidden"),
    }));
    for (const element of background) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        sidecarRef.current?.querySelectorAll<HTMLElement>(
          [
            'button:not([disabled])',
            '[href]',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
          ].join(", "),
        ) ?? [],
      ).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) {
        event.preventDefault();
        sidecarRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", trapFocus);
    const frame = window.requestAnimationFrame(() => {
      sidecarRef.current
        ?.querySelector<HTMLElement>('button[aria-label="Close Ask Mosaic"]')
        ?.focus();
    });
    return () => {
      document.body.style.overflow = previousOverflow;
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", trapFocus);
      for (const { element, inert, ariaHidden } of prior) {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
    };
  }, [modal, open]);

  /**
   * Follow the newest exchange, including while it streams.
   *
   * `scrollTop` rather than `scrollTo`, because this runs on every delta and an
   * animated scroll would be re-targeted mid-flight on each one.
   */
  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    thread.scrollTop = thread.scrollHeight;
  }, [open, latest?.id, latest?.response, latest?.error, streamedLength]);

  if (!open) return null;

  return (
    <div className="ask-mosaic-layer" ref={layerRef}>
      <button
        className="ask-mosaic-backdrop"
        type="button"
        aria-label="Close Ask Mosaic"
        onClick={onClose}
      />
      <aside
        ref={sidecarRef}
        className="ask-mosaic-sidecar"
        role={modal ? "dialog" : "complementary"}
        aria-modal={modal ? "true" : undefined}
        aria-labelledby="ask-mosaic-title"
        tabIndex={-1}
      >
        <header className="ask-mosaic-header">
          <div>
            <span><Sparkles size={19} /></span>
            <div>
              <p>Your intelligent shopping guide</p>
              <h2 id="ask-mosaic-title">Ask Mosaic</h2>
            </div>
          </div>
          <button type="button" aria-label="Close Ask Mosaic" onClick={onClose}>
            <X size={20} />
          </button>
        </header>

        <div className="ask-mosaic-body" ref={threadRef}>
          {turns.length ? (
            turns.map((turn, index) => (
              <Turn
                key={turn.id}
                turn={turn}
                isLatest={index === turns.length - 1}
                imageByProductId={imageByProductId}
                highlightedProductId={highlightedProductId}
                onRun={onRun}
                onHighlight={onHighlight}
                onSelectProduct={onSelectProduct}
              />
            ))
          ) : (
            <EntryState starters={starters} onRun={onRun} />
          )}
        </div>

        {/* Pinned under the thread, where a conversation puts it. It used to sit
            above the answer, so the reply to a question appeared below the field
            that would replace it. */}
        <div className="ask-mosaic-composer">
          {contextFilters.length ? (
            <div
              className="ask-mosaic-context"
              aria-label="Active filters passed to Ask Mosaic"
            >
              <span>Active filters</span>
              <strong>{contextFilters.join(" · ")}</strong>
            </div>
          ) : null}
          <SearchComposer
            compact
            autoFocus={!modal}
            clearOnSubmit
            initialValue={seedQuery}
            inputLabel="Ask Mosaic request"
            pending={pending}
            submitLabel="Ask"
            placeholder={turns.length ? "Ask a follow-up" : "What are you shopping for?"}
            onSubmit={onRun}
          />
        </div>
      </aside>
    </div>
  );
}
