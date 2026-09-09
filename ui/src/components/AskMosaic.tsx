import {
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Eraser,
  FileText,
  GitCompareArrows,
  LoaderCircle,
  PencilLine,
  RotateCcw,
  Send,
  ShoppingBag,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { cartQuantityLimit, useCommerce } from "../commerce";
import {
  formatAvailability,
  formatCategoryKey,
  formatPrice,
} from "../format";
import { productImage } from "../media";
import {
  FINAL_LABEL,
  FUSED_LABEL,
  armLanguage,
} from "../retrievalLanguage";
import { lockBodyScroll } from "../scrollLock";
import { useTypewriterReveal } from "../useTypewriterReveal";
import type { mosaicLabManifest } from "../labMissions";
import type {
  AgentCitation,
  AgentPartial,
  AgentPlanStep,
  AgentResponse,
  ProductSummary,
  ResultSignals,
  SearchFilters,
  ToolTraceStep,
} from "../types";
import { Criteria, Searches } from "./agentAnswerParts";
import { AgentRetrievalReceipt } from "./RetrievalReceipt";
import { SearchComposer } from "./SearchComposer";
import { ProductAnswer } from "./ProductAnswer";
import { ResultProductCard } from "./ResultProductCard";

export type AssistStage = "understand" | "retrieve" | "rank" | "answer";
export type AssistExecutionPath = "focused_follow_up" | "full_retrieval";

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
  /** Keeps a saved conversation from replacing results for a different Shop request. */
  contextKey?: string;
  response: AgentResponse | null;
  /** True only after the stream's terminal `complete` event has arrived. */
  completed: boolean;
  /**
   * Retrieval that has landed while the run is still going, so the stage that
   * is in progress has something real to show. Superseded by `response`.
   */
  partial: AgentPartial | null;
  /** Text delivered so far by `answer_delta`. Empty until the first token. */
  streamed: string;
  stage: AssistStage | null;
  /**
   * `Date.now()` at the moment `stage` last changed, so the step that is working
   * can report how long it has been working.
   *
   * Synthesis is the long pole: the answer cannot be shown until it has been
   * checked against the citations it claims, so the last step sits at "in
   * progress" for as long as that model call takes. With nothing counting, a
   * measured fourteen seconds read as a hung panel.
   */
  stageStartedAt: number;
  executionPath: AssistExecutionPath;
  stageDetail: string;
  error: string;
  loading: boolean;
}

const fullRetrievalStages: Array<{
  id: AssistStage;
  label: string;
  title: string;
  description: string;
}> = [
  {
    id: "understand",
    label: "Request",
    title: "Search criteria",
    description: "Identifying requirements and catalog filters from your request.",
  },
  {
    id: "retrieve",
    label: "Retrieval",
    title: "Product shortlist",
    description: "Finding relevant products within your search criteria.",
  },
  {
    id: "rank",
    label: "Comparison",
    title: "Product comparison",
    description: "Comparing features and trade-offs using catalog records.",
  },
  {
    id: "answer",
    label: "Attribution",
    title: "Supporting evidence",
    description: "Linking recommendations to their source records.",
  },
];

const focusedFollowUpStages: typeof fullRetrievalStages = [
  {
    id: "understand",
    label: "Request",
    title: "Follow-up context",
    description: "Interpreting your follow-up in the context of the current shortlist.",
  },
  {
    id: "rank",
    label: "Comparison",
    title: "Product comparison",
    description: "Reviewing the product records relevant to your follow-up.",
  },
  {
    id: "answer",
    label: "Attribution",
    title: "Supporting evidence",
    description: "Checking the new answer against freshly retrieved evidence.",
  },
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
 * One chip per arm that retrieved the row.
 *
 * `RankSignal.rank` is null for an arm that never retrieved the product, so this
 * reports measured arm membership. The reference design put a "96% match" badge
 * on every row; no such number exists in `ResultSignals`, and the reranker score
 * is the one bounded relevance figure the service actually produces — which is
 * why it is the last chip and carries its own word rather than a bare decimal.
 *
 * The labels used to be a third set: "Your exact words", "Close spellings",
 * "What you meant", against the product card's "Exact terms" / "Close spelling" /
 * "Meaning match" for the same three arms.
 */
export function retrievalChips(signals: ResultSignals | null | undefined): string[] {
  if (!signals) return ["In the shortlist"];
  const matched = armLanguage
    .filter((arm) => signals[arm.key].rank != null)
    .map((arm) => arm.label);
  const chips = matched.length ? matched : ["Carried in by combined ranking"];
  if (signals.rerank_score != null) {
    chips.push(`Rerank score ${signals.rerank_score.toFixed(2)}`);
  }
  return chips;
}

function escapePattern(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Emphasize only products present in the grounded recommendation contract.
 *
 * The cited synthesis model is not required to author presentation Markdown.
 * Applying emphasis at the UI boundary makes product names consistent without
 * changing the answer of record or inferring names from untrusted prose.
 */
export function boldRecommendationNames(
  answer: string,
  recommendations: ProductSummary[],
) {
  const names = Array.from(
    new Set(
      recommendations.flatMap((product) => [
        product.title.trim(),
        `${product.brand} ${product.model}`.trim(),
      ]),
    ),
  )
    .filter((name) => name.length >= 5)
    .sort((left, right) => right.length - left.length);
  if (!names.length) return answer;

  const productName = new RegExp(
    `(${names.map(escapePattern).join("|")})`,
    "gi",
  );
  return answer
    .split(/(\*\*[^*]+\*\*)/g)
    .map((segment) => (
      segment.startsWith("**")
        ? segment
        : segment.replace(productName, "**$1**")
    ))
    .join("");
}

/**
 * Seconds elapsed on the step that is working, ticking.
 *
 * Wall clock against the moment the service announced the step, so this is a
 * measurement rather than a progress animation: nothing here estimates how much
 * longer the step will take, because nothing knows.
 */
function StageElapsed({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(() => Date.now() - since);

  useEffect(() => {
    setElapsed(Date.now() - since);
    const timer = window.setInterval(() => {
      setElapsed(Date.now() - since);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [since]);

  const seconds = Math.max(0, Math.floor(elapsed / 1000));
  if (seconds < 1) return null;
  return <small className="ask-mosaic-stage-elapsed">{seconds}s</small>;
}

function StageRail({
  actualStage,
  complete,
  executionPath,
  failed,
  presentedStage,
  stageDetail,
  stageStartedAt,
  panels,
  onPresentationProgress,
}: {
  actualStage: AssistStage | null;
  complete: boolean;
  executionPath: AssistExecutionPath;
  failed: boolean;
  presentedStage: AssistStage;
  stageDetail: string;
  stageStartedAt: number;
  panels: Partial<Record<AssistStage, ReactNode>>;
  onPresentationProgress?: () => void;
}) {
  const stages = executionPath === "focused_follow_up"
    ? focusedFollowUpStages
    : fullRetrievalStages;
  const actualIndex = complete
    ? stages.length
    : actualStage
    ? stages.findIndex((item) => item.id === actualStage)
    : 0;
  const presentedIndex = Math.max(
    0,
    stages.findIndex((item) => item.id === presentedStage),
  );
  return (
    <section className="ask-mosaic-timeline" aria-label="Retrieval activity">
      <p className="ask-mosaic-timeline-heading">
        <GitCompareArrows size={14} aria-hidden="true" />
        Retrieval activity
      </p>
      <ol className="ask-mosaic-progress" aria-label="Ask Mosaic activity">
        {stages.map((stage, index) => {
          const state: AssistStageState = index < presentedIndex
            ? "complete"
            : index > presentedIndex
              ? "pending"
              : failed
                ? "failed"
                : complete || index < actualIndex
                  ? "complete"
                  : "active";
          const stateLabel = state === "complete"
            ? "Complete"
            : state === "active"
              ? "In progress"
              : state === "failed"
                ? "Needs attention"
              : "Pending";
          const description = (state === "active" || state === "failed")
            && stage.id === actualStage
            && stageDetail
            ? stageDetail
            : stage.description;
          return (
            <li className={state} key={stage.id}>
              {/* Keeping labels inside the card preserves space for their text
                  and the comparison at narrow drawer widths. */}
              <span className="ask-mosaic-stage-rail">
                <span className="ask-mosaic-stage-node" aria-hidden="true">
                  {state === "complete"
                    ? <Check size={16} strokeWidth={2.25} />
                    : state === "active"
                      ? <LoaderCircle className="spin" size={16} />
                      : state === "failed"
                        ? <X size={16} />
                      : index + 1}
                </span>
              </span>
              <StageDisclosure
                description={description}
                elapsedSince={
                  state === "active" && stage.id === actualStage && !complete
                    ? stageStartedAt
                    : null
                }
                label={stage.label}
                onPresentationProgress={onPresentationProgress}
                panel={panels[stage.id]}
                presented={index === presentedIndex}
                state={state}
                stateLabel={stateLabel}
                title={stage.title}
              />
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/**
 * Minimum reading beat when the service outruns the interface.
 *
 * Real tool calls normally take longer than this. The dwell only matters when
 * several SSE milestones land in one React batch, where it prevents the middle
 * steps from being skipped without turning the timeline into a second wait.
 */
export const stageDwellMs = 700;

function useProgressiveStage(
  executionPath: AssistExecutionPath,
  actualStage: AssistStage | null,
  instant: boolean,
): AssistStage {
  const stages = executionPath === "focused_follow_up"
    ? focusedFollowUpStages
    : fullRetrievalStages;
  const [presentedStage, setPresentedStage] = useState<AssistStage>(() => {
    const actualIndex = actualStage
      ? stages.findIndex((stage) => stage.id === actualStage)
      : -1;
    return instant && actualIndex >= 0
      ? stages[actualIndex].id
      : stages[0].id;
  });
  const presentedIndex = Math.max(
    0,
    stages.findIndex((stage) => stage.id === presentedStage),
  );
  const matchedActualIndex = actualStage
    ? stages.findIndex((stage) => stage.id === actualStage)
    : -1;
  const actualIndex = matchedActualIndex >= 0
    ? matchedActualIndex
    : presentedIndex;

  useEffect(() => {
    if (actualIndex <= presentedIndex) return;
    if (instant) {
      setPresentedStage(stages[actualIndex].id);
      return;
    }
    const timer = window.setTimeout(() => {
      setPresentedStage(stages[Math.min(presentedIndex + 1, actualIndex)].id);
    }, stageDwellMs);
    return () => window.clearTimeout(timer);
  }, [actualIndex, instant, presentedIndex, stages]);

  return stages[presentedIndex].id;
}

type AssistStageState = "complete" | "active" | "failed" | "pending";

function StageDisclosure({
  description,
  elapsedSince,
  label,
  onPresentationProgress,
  panel,
  presented,
  state,
  stateLabel,
  title,
}: {
  description: string;
  /** When this step started, or null unless it is the one working. */
  elapsedSince: number | null;
  label: string;
  onPresentationProgress?: () => void;
  panel: ReactNode;
  /** This is the one stage the progressive timeline is currently presenting. */
  presented: boolean;
  state: AssistStageState;
  stateLabel: string;
  title: string;
}) {
  /**
   * Scope an explicit reader choice to the state in which it was made. A stage
   * changing from active to complete returns to the progressive default, while a
   * completed stage the reader reopens stays open as later stages arrive.
   */
  const [override, setOverride] = useState<{
    state: AssistStageState;
    open: boolean;
  } | null>(null);
  const reduceMotion = useReducedMotion();
  const hasPanel = Boolean(panel) && state !== "pending";
  const open = hasPanel && (
    override?.state === state ? override.open : presented
  );

  return (
    <section className="ask-mosaic-stage-panel">
      <button
        className="ask-mosaic-stage-summary"
        type="button"
        aria-expanded={hasPanel ? open : undefined}
        // Nothing to disclose yet: a pending stage has not run, and a stage that
        // is working has produced nothing until its first tool returns. The
        // control used to stay enabled and expanded through both, so an active
        // card opened onto an empty box.
        disabled={!hasPanel}
        onClick={() => {
          setOverride({ state, open: !open });
        }}
      >
        <span className="ask-mosaic-stage-copy">
          <span className="ask-mosaic-stage-eyebrow">
            <small className="ask-mosaic-stage-label">{label}</small>
            <small className="ask-mosaic-stage-state">{stateLabel}</small>
            {elapsedSince ? <StageElapsed since={elapsedSince} /> : null}
          </span>
          <strong>{title}</strong>
          <span className="ask-mosaic-stage-detail">{description}</span>
        </span>
        {hasPanel ? (
          <ChevronDown
            className={open
              ? "ask-mosaic-stage-chevron open"
              : "ask-mosaic-stage-chevron"}
            size={17}
          />
        ) : null}
      </button>
      {/* Height, not display. The content was mounted and unmounted outright, so
          a step folding itself away after its dwell snapped the whole panel up by
          however tall its result was. The padding and rule live on the inner
          element, or a collapsed panel would still draw 16px of them. */}
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="content"
            style={{ overflow: "hidden" }}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onAnimationComplete={onPresentationProgress}
            transition={reduceMotion
              ? { duration: 0 }
              : {
                duration: 0.24,
                ease: [0.23, 1, 0.32, 1],
                opacity: { duration: 0.16 },
              }}
          >
            <div className="ask-mosaic-stage-content">{panel}</div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

/** A value the comparison table can print without inventing anything. */
function comparableAttribute(value: unknown): value is string | number | boolean {
  return (
    (typeof value === "string" && value.length > 0 && value.length <= 40)
    || typeof value === "number"
    || typeof value === "boolean"
  );
}

function attributeText(value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * Side-by-side catalog facts for the top of the shortlist.
 *
 * Every row is a field of the product record: price, rating, availability,
 * and whichever attributes all compared products carry. The reference design
 * scored candidates "Very good" / "Excellent" per factor; no such judgment
 * exists in the contract, so none is printed.
 */
function CompareMatrix({ candidates }: { candidates: ProductSummary[] }) {
  const products = candidates.slice(0, 3);
  if (products.length < 2) return null;
  const sharedAttributes = Object.entries(products[0].attributes)
    .filter(([name, value]) => (
      comparableAttribute(value)
      && products.every((product) => comparableAttribute(product.attributes[name]))
    ))
    .map(([name]) => name)
    .slice(0, 3);
  return (
    <section className="ask-mosaic-section ask-mosaic-comparison">
      <header>
        <GitCompareArrows size={18} />
        <div>
          <h3>Side by side, on catalog data</h3>
          <p>Every value below comes from the product records in this shortlist.</p>
        </div>
      </header>
      <div className="ask-mosaic-compare-scroll">
        <table className="ask-mosaic-compare">
          <thead>
            <tr>
              <td />
              {products.map((product, index) => (
                <th
                  className={index === 0 ? "leader" : undefined}
                  key={product.product_id}
                  scope="col"
                >
                  <small>{String(index + 1).padStart(2, "0")}</small>
                  {`${product.brand} ${product.model}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Price</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {formatPrice(product.price_cents, product.currency)}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Rating</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {product.rating != null
                    ? `${product.rating.toFixed(1)} (${product.review_count})`
                    : "-"}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Availability</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {formatAvailability(product.availability)}
                </td>
              ))}
            </tr>
            {sharedAttributes.map((name) => (
              <tr key={name}>
                <th scope="row">{name.replace(/_/g, " ")}</th>
                {products.map((product, index) => (
                  <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                    {attributeText(product.attributes[name] as string | number | boolean)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface ShortlistProps {
  candidates: ProductSummary[];
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

function Shortlist({
  candidates,
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
          <h3>The shortlist</h3>
          <p>Real catalog products, in the order search ranked them.</p>
        </div>
      </header>
      <ol className="ask-mosaic-shortlist">
        {candidates.slice(0, 4).map((product, index) => (
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
              {/* Phrasing content only. A button may not contain `div` or `ol`,
                  and the row carries four distinct fields that each need their
                  own grid area. */}
              <span className="ask-mosaic-shortlist-copy">
                {index === 0 ? <span className="ask-mosaic-card-pick">Best match</span> : null}
                <strong>{product.brand} {product.model}</strong>
                <small>{formatCategoryKey(product.category_key)}</small>
              </span>
              <span className="ask-mosaic-shortlist-meta">
                <strong>{formatPrice(product.price_cents, product.currency)}</strong>
                {product.rating != null ? (
                  <small>{product.rating.toFixed(1)} · {product.review_count} reviews</small>
                ) : null}
              </span>
              <span
                className="ask-mosaic-shortlist-signals"
                aria-label="Why this candidate was retrieved"
              >
                {retrievalChips(product.signals).map((chip) => (
                  <span key={chip}>{chip}</span>
                ))}
              </span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Why the leader leads, in the shopper's vocabulary.
 *
 * The rows read "FTS / pg_trgm / Vector / RRF / Reranker / Final" — four Postgres
 * and information-retrieval terms inside a shopping concierge. The numbers are
 * unchanged, and every one of them is this product's own position, so each is
 * printed with a `#`. The mechanism behind each row is named on the Playground,
 * beside the SQL that produced it.
 */
function Ranking({ candidates }: { candidates: ProductSummary[] }) {
  const winner = candidates[0];
  const signals = winner?.signals;
  if (!signals) return null;
  return (
    <details className="ask-mosaic-ranking">
      <summary>
        <span>Why this result ranks first</span>
        <small>{winner.model}</small>
      </summary>
      <dl>
        {armLanguage.map((arm) => (
          <div key={arm.key}>
            <dt>{arm.label}</dt>
            <dd>{signals[arm.key].rank ? `#${signals[arm.key].rank}` : "-"}</dd>
          </div>
        ))}
        <div>
          <dt>{FUSED_LABEL}</dt>
          <dd>#{signals.pre_rerank_rank}</dd>
        </div>
        <div>
          <dt>Rerank score</dt>
          <dd>
            {signals.rerank_score?.toFixed(3) ?? "-"}
            {signals.rerank_rank ? ` (#${signals.rerank_rank})` : ""}
          </dd>
        </div>
        {signals.exact_sku_match ? (
          <div>
            <dt>Exact model match</dt>
            <dd>Yes</dd>
          </div>
        ) : null}
        <div>
          <dt>{FINAL_LABEL}</dt>
          <dd>#{signals.final_rank}</dd>
        </div>
      </dl>
    </details>
  );
}

function Evidence({ citations }: { citations: AgentCitation[] }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <FileText size={17} />
        Evidence it cited
        <span>{citations.length}</span>
      </summary>
      <ol className="ask-mosaic-evidence">
        {citations.map((citation) => (
          <li key={`${citation.number}-${citation.evidence_id}`}>
            <span>[{citation.number}]</span>
            <div>
              <strong>{citation.title}</strong>
              <p>{citation.quote}</p>
              <small>
                Record #{citation.evidence_id} · {citation.evidence_type.replace(/_/g, " ")} ·{" "}
                {citation.revision}
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
function Activity({ trace }: { trace: ToolTraceStep[] }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <CircleCheck size={17} />
        What the agent did
        <span>{trace.length}</span>
      </summary>
      <ol className="ask-mosaic-activity">
        {trace.map((step) => (
          <li className={step.outcome} key={step.sequence}>
            <span>{String(step.sequence).padStart(2, "0")}</span>
            <div>
              <strong>{toolLabels.get(step.tool) ?? step.tool}</strong>
              <code className="ask-mosaic-tool-fn">{step.tool}</code>
              {step.origin === "controller_fallback" ? (
                <small>Completed by the app, not the model</small>
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
 * The catalog-gap notice a declined answer renders instead of a shortlist.
 *
 * A declined `AgentResponse` carries an empty `recommendations` and
 * `citations` on purpose: the agent issued at least one search and every one
 * of them named something the catalog does not carry, so there is nothing
 * grounded to present. This reads as its own outcome rather than as an
 * ordinary answer over an empty shortlist, which is what shipped before this
 * block existed.
 */
function DeclinedNotice({ answer }: { answer: string }) {
  return (
    <section className="ask-mosaic-declined" aria-label="Declined answer">
      <h3>Nothing in the catalog matches part of this request</h3>
      <p>{answer}</p>
      <small>
        This is a catalog gap, not a retrieval fault. Try different words or
        drop the term named above.
      </small>
    </section>
  );
}

/**
 * The recommended products, buyable.
 *
 * `recommendations` is the cited set the answer of record was written from, so
 * these are the same products the prose names - not a second, looser shortlist.
 * The bag button is the cart the rest of the store uses, so a participant can
 * finish the errand the answer started instead of reading about it.
 */
function ShoppingResultCard({ product, position, imageByProductId, onHighlight, onSelectProduct }: {
  product: ProductSummary; position: number; imageByProductId: Map<number, string>;
  onHighlight: (productId: number | null) => void; onSelectProduct: (productId: number) => void;
}) {
  const { addItem, itemQuantity } = useCommerce();
  const inBag = itemQuantity(product.product_id);
  const limit = cartQuantityLimit(product);
  return <ResultProductCard product={product} imageSrc={imageByProductId.get(product.product_id)} rank={position}
    onHighlight={onHighlight} onSelect={onSelectProduct}
    footer={<button className={inBag ? "ask-mosaic-pick-add in-bag" : "ask-mosaic-pick-add"} type="button" disabled={!limit || inBag >= limit} title={limit ? undefined : "Out of stock"} onClick={() => addItem(product)}><ShoppingBag size={14} aria-hidden="true" />{inBag ? `In bag (${inBag})` : "Add to bag"}</button>} />;
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
          `Explain why ${first.model} ranked first, using what the search and the evidence show.`,
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
  onEdit: (query: string) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
  /** Keeps each newly presented stage in view inside the scrolling drawer. */
  onStageProgress?: () => void;
  /**
   * Fires as the reveal advances so the thread can keep the writing line in
   * view. Only the latest turn receives it; settled turns have nothing to
   * report.
   */
  onRevealProgress?: () => void;
}

function Turn({
  turn,
  isLatest,
  imageByProductId,
  highlightedProductId,
  onRun,
  onEdit,
  onHighlight,
  onSelectProduct,
  onStageProgress,
  onRevealProgress,
}: TurnProps) {
  const response = turn.response;
  const reduceMotion = useReducedMotion();
  const [startedLive] = useState(turn.loading);
  const instantPresentation = Boolean(
    reduceMotion || !startedLive || turn.error,
  );
  const actualStage = response ? "answer" : turn.stage;
  const presentedStage = useProgressiveStage(
    turn.executionPath,
    actualStage,
    instantPresentation,
  );
  const answerStagePresented = presentedStage === "answer";
  const [answerVisible, setAnswerVisible] = useState(
    () => Boolean(response && turn.completed && !turn.error),
  );

  useEffect(() => {
    if (!response || !answerStagePresented || turn.error) {
      setAnswerVisible(false);
      return;
    }
    if (instantPresentation) {
      setAnswerVisible(true);
      return;
    }
    const timer = window.setTimeout(() => setAnswerVisible(true), 180);
    return () => window.clearTimeout(timer);
  }, [answerStagePresented, instantPresentation, response, turn.error]);

  const reveal = useTypewriterReveal(
    turn.streamed || response?.answer || "",
    turn.loading,
    answerVisible,
    reduceMotion ?? false,
  );
  /** The stream has closed and the typewriter has finished writing it out. */
  const answerSettled = turn.completed && reveal.done;
  const presentedStageTitle = (
    turn.executionPath === "focused_follow_up"
      ? focusedFollowUpStages
      : fullRetrievalStages
  ).find((stage) => stage.id === presentedStage)?.title ?? "Working";
  useEffect(() => {
    onRevealProgress?.();
  }, [reveal.text.length, onRevealProgress]);
  useEffect(() => {
    onStageProgress?.();
  }, [answerVisible, onStageProgress, presentedStage]);
  /**
   * Whichever retrieval has landed. The finished response supersedes the partial
   * because its shortlist is the cited one; until it arrives, the partial is what
   * the tools have actually returned. A stage with nothing yet gets `null`, which
   * is what keeps its card from opening onto an empty box.
   */
  const plan: AgentPlanStep[] = response?.plan ?? turn.partial?.plan ?? [];
  const candidates: ProductSummary[] =
    response?.recommendations ?? turn.partial?.candidates ?? [];
  const trace: ToolTraceStep[] = response?.trace ?? turn.partial?.trace ?? [];
  const citations: AgentCitation[] = response?.citations ?? [];
  // A declined answer names an absence rather than a recommendation:
  // `recommendations` and `citations` are empty by contract, so the shortlist
  // and the compare/cite panels below have nothing real to show. The steps
  // timeline and the searches list stay, because they are what was actually
  // tried, and that is what a shopper reading a decline needs to see.
  const declined = response?.outcome === "declined";
  const comparison = !declined && candidates.length > 1
    ? (
      <>
        <CompareMatrix candidates={candidates} />
        <Ranking candidates={candidates} />
      </>
    )
    : null;
  const stagePanels: Partial<Record<AssistStage, ReactNode>> = {
    understand: plan.length ? <Criteria plan={plan} /> : null,
    retrieve: (!declined && candidates.length) || plan.length
      ? (
        <>
          {!declined && candidates.length ? (
            <Shortlist
              candidates={candidates}
              imageByProductId={imageByProductId}
              highlightedProductId={highlightedProductId}
              onHighlight={onHighlight}
              onSelectProduct={onSelectProduct}
            />
          ) : null}
          {plan.length ? <Searches plan={plan} /> : null}
        </>
      )
      : null,
    rank: comparison,
    answer: (!declined && citations.length) || trace.length
      ? (
        <>
          {!declined && citations.length ? <Evidence citations={citations} /> : null}
          {trace.length ? <Activity trace={trace} /> : null}
        </>
      )
      : null,
  };
  return (
    <article className="ask-mosaic-turn">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {turn.error
          ? "Ask Mosaic could not finish this request."
          : answerSettled
            ? "Ask Mosaic recommendation complete."
            : `${presentedStageTitle}. In progress.`}
      </p>
      <div className="ask-mosaic-ask">
        <span className="ask-mosaic-request-icon" aria-hidden="true">
          <Sparkles size={18} />
        </span>
        <div className="ask-mosaic-request-copy">
          <span>You asked</span>
          <p>{turn.question}</p>
        </div>
        {isLatest && !turn.loading ? (
          <span className="ask-mosaic-request-actions">
            <button
              className="ask-mosaic-edit-request"
              type="button"
              onClick={() => onEdit(turn.question)}
            >
              <PencilLine size={13} aria-hidden="true" />
              Edit request
            </button>
            <button
              className="ask-mosaic-ask-again"
              type="button"
              onClick={() => onRun(turn.question)}
            >
              <RotateCcw size={13} aria-hidden="true" />
              Ask again
            </button>
          </span>
        ) : null}
      </div>

      {turn.loading || turn.stage || response ? (
        <details className="ask-mosaic-process" open={!answerVisible || Boolean(turn.error)}>
          <summary>
            <span>{turn.error ? "Request details" : answerVisible ? "Steps and sources" : "Search in progress"}</span>
            <small>{turn.error ? "Request interrupted" : answerVisible ? "Inspect what Mosaic used" : presentedStageTitle}</small>
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
        <StageRail
          actualStage={actualStage}
          complete={answerSettled}
          executionPath={turn.executionPath}
          failed={Boolean(turn.error)}
          presentedStage={presentedStage}
          stageDetail={turn.stageDetail}
          stageStartedAt={turn.stageStartedAt}
          panels={stagePanels}
          onPresentationProgress={onStageProgress}
        />
        </details>
      ) : null}

      {turn.error ? (
        <div className="ask-mosaic-error" role="alert">
          <strong>Mosaic could not finish this request.</strong>
          <span>{turn.error}</span>
          <small>Press Ask again to retry. If it keeps failing, the API session may need refreshing.</small>
        </div>
      ) : null}

      <AnimatePresence initial={false}>
        {response && answerVisible && !turn.error ? (
          <motion.div
            className="ask-mosaic-answer-sequence"
            initial={{ opacity: 0, transform: "translateY(7px)" }}
            animate={{ opacity: 1, transform: "translateY(0)" }}
            exit={{ opacity: 0, transform: "translateY(4px)" }}
            transition={{
              duration: reduceMotion ? 0 : 0.22,
              ease: [0.23, 1, 0.32, 1],
            }}
          >
          {/* `streaming` draws the caret. It stays up past the last SSE chunk
              until the typewriter finishes writing the text out, because the
              caret marks the visible write, not the network. */}
          <section
            className={answerSettled ? "ask-mosaic-answer" : "ask-mosaic-answer streaming"}
          >
            {declined ? (
              <DeclinedNotice answer={reveal.text} />
            ) : (
              <>
                <p>
                  <Sparkles size={14} />
                  {answerSettled ? "Final recommendation" : "Writing the answer"}
                  {response.citations.length ? (
                    <span className="ask-mosaic-cited-support">
                      <CircleCheck size={12} aria-hidden="true" />
                      Backed by evidence
                    </span>
                  ) : answerSettled ? (
                    <span className="ask-mosaic-cited-support is-missing">
                      No evidence cited
                    </span>
                  ) : null}
                </p>
                {/* The wrapper bounds the caret: the shortlist below is part of
                    the same section, and a section-level `:last-child` put the
                    caret after the product cards instead of the prose being
                    written. */}
                <div className="ask-mosaic-prose">
                  <ProductAnswer text={boldRecommendationNames(reveal.text, response.recommendations)} products={response.recommendations} citations={response.citations} complete={answerSettled} label="Recommended products" renderCard={(product, position) => <ShoppingResultCard product={product} position={position} imageByProductId={imageByProductId} onHighlight={onHighlight} onSelectProduct={onSelectProduct} />} />
                </div>
                {/* A fail-closed run is a fact about this answer, and an absent
                    badge does not state it. */}
                {answerSettled && !response.citations.length ? (
                  <p className="ask-mosaic-uncited-note">
                    No product record backs this answer, so read it as a
                    suggestion rather than a checked recommendation. Ask again,
                    or add a detail such as a budget or a category.
                  </p>
                ) : null}
              </>
            )}
          </section>

          {answerSettled && !declined ? (
            <motion.div
              className="ask-mosaic-answer-aftermath"
              initial={{ opacity: 0, transform: "translateY(6px)" }}
              animate={{ opacity: 1, transform: "translateY(0)" }}
              transition={{
                duration: reduceMotion ? 0 : 0.24,
                delay: reduceMotion ? 0 : 0.05,
                ease: [0.23, 1, 0.32, 1],
              }}
            >
              <AgentRetrievalReceipt
                citations={citations}
                executionPath={turn.executionPath}
                plan={plan}
                products={candidates}
                trace={trace}
              />

              {isLatest && !turn.loading ? (
                <FollowUps response={response} onRun={onRun} />
              ) : null}
            </motion.div>
          ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </article>
  );
}

type WorkspaceRequest = typeof mosaicLabManifest.playground.requests[number];

function EntryState({ suggestions, onRun }: {
  suggestions: WorkspaceRequest[];
  onRun: (query: string, filters?: SearchFilters) => void;
}) {
  return <section className="ask-mosaic-empty">
    <div className="ask-mosaic-welcome">
      <h3>Make room for better work.</h3>
      <p>Tell me about your day, your desk and your budget. I’ll help you find the pieces that fit.</p>
    </div>
    {suggestions.length ? <div className="ask-mosaic-starters">
      <h4>A place to start</h4>
      <ul aria-label="Example questions">{suggestions.map((suggestion) => <li key={suggestion.id}>
        <button type="button" aria-label={suggestion.query} onClick={() => onRun(suggestion.query, suggestion.filters)}>
          <span className="ask-mosaic-starter-path">{suggestion.shop_label}</span>
          <ArrowUpRight className="ask-mosaic-starter-go" size={17} aria-hidden="true" />
          {suggestion.query !== suggestion.shop_label ? <span className="ask-mosaic-starter-query">{suggestion.query}</span> : null}
        </button>
      </li>)}</ul>
    </div> : null}
    <p className="ask-mosaic-entry-note">I can compare products, check specifications and explain my picks with sources. You can refine the shortlist as we go.</p>
  </section>;
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
  suggestions: WorkspaceRequest[];
  /** Photographs the Shop grid assigned, so the rail agrees with the cards. */
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onClose: () => void;
  /** Discards the conversation and leaves the panel open on the entry state. */
  onClear: () => void;
  onRun: (query: string, filters?: SearchFilters) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

export function AskMosaic({
  open,
  seedQuery,
  contextFilters,
  turns,
  pending,
  suggestions,
  imageByProductId,
  highlightedProductId,
  onClose,
  onClear,
  onRun,
  onHighlight,
  onSelectProduct,
}: AskMosaicProps) {
  const [modal, setModal] = useState(
    () => window.matchMedia?.("(max-width: 1180px)").matches ?? false,
  );
  const [composerDraft, setComposerDraft] = useState({
    value: seedQuery,
    version: 0,
  });
  const layerRef = useRef<HTMLDivElement | null>(null);
  const sidecarRef = useRef<HTMLElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  const followTailRef = useRef(true);
  const latest = turns.length ? turns[turns.length - 1] : null;

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    setComposerDraft((current) => ({
      value: seedQuery,
      version: current.version + 1,
    }));
  }, [seedQuery]);

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
    const unlockScroll = lockBodyScroll();
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
      unlockScroll();
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", trapFocus);
      for (const { element, inert, ariaHidden } of prior) {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
    };
  }, [modal, open]);

  /** Keep following only while the reader remains at the live edge. */
  const followReveal = useCallback(() => {
    const thread = threadRef.current;
    if (thread && followTailRef.current) thread.scrollTop = thread.scrollHeight;
  }, []);

  const handleThreadScroll = useCallback(() => {
    const thread = threadRef.current;
    if (!thread) return;
    followTailRef.current = (
      thread.scrollHeight - thread.scrollTop - thread.clientHeight
    ) <= 48;
  }, []);

  /** A newly opened conversation or a question the reader just sent owns focus. */
  useEffect(() => {
    if (!open) return;
    followTailRef.current = true;
    const frame = window.requestAnimationFrame(followReveal);
    return () => window.cancelAnimationFrame(frame);
  }, [open, latest?.id, followReveal]);

  if (!open) return null;

  const editRequest = (question: string) => {
    setComposerDraft((current) => ({
      value: question,
      version: current.version + 1,
    }));
    window.requestAnimationFrame(() => {
      const input = sidecarRef.current?.querySelector<HTMLInputElement>(
        ".ask-mosaic-composer input",
      );
      input?.focus();
      input?.setSelectionRange(question.length, question.length);
    });
  };

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
              <h2 id="ask-mosaic-title">Ask Mosaic</h2>
              <p>Your workspace, considered.</p>
            </div>
          </div>
          {/* Only once there is something to discard. On the entry state the
              control would clear nothing, and it would sit beside the starters
              it appears to threaten. */}
          <span className="ask-mosaic-header-actions">
            {turns.length ? (
              <button
                className="ask-mosaic-clear-chat"
                type="button"
                onClick={onClear}
              >
                <Eraser size={14} aria-hidden="true" />
                Clear chat
              </button>
            ) : null}
            <button
              className="ask-mosaic-header-close"
              type="button"
              aria-label="Close Ask Mosaic"
              onClick={onClose}
            >
              <X size={20} />
            </button>
          </span>
        </header>

        <div
          className="ask-mosaic-body"
          ref={threadRef}
          onScroll={handleThreadScroll}
        >
          {turns.length ? (
            turns.map((turn, index) => (
              <Turn
                key={turn.id}
                turn={turn}
                isLatest={index === turns.length - 1}
                imageByProductId={imageByProductId}
                highlightedProductId={highlightedProductId}
                onRun={onRun}
                onEdit={editRequest}
                onHighlight={onHighlight}
                onSelectProduct={onSelectProduct}
                onStageProgress={index === turns.length - 1 ? followReveal : undefined}
                onRevealProgress={index === turns.length - 1 ? followReveal : undefined}
              />
            ))
          ) : (
            <EntryState
              suggestions={suggestions}
              onRun={onRun}
            />
          )}
        </div>

        {/* Pinned under the thread, where a conversation puts it. It used to sit
            above the answer, so the reply to a question appeared below the field
            that would replace it. */}
        <div className="ask-mosaic-composer">
          {contextFilters.length ? (
            <div
              className="ask-mosaic-context"
              aria-label="Current search filters, passed to Ask Mosaic"
            >
              <span>Search filters</span>
              <strong>{contextFilters.join(" · ")}</strong>
            </div>
          ) : null}
          <SearchComposer
            key={composerDraft.version}
            compact
            autoFocus={!modal}
            clearOnSubmit
            initialValue={composerDraft.value}
            inputLabel="Ask Mosaic request"
            pending={pending}
            submitIcon={<Send size={18} aria-hidden="true" />}
            submitLabel="Send request"
            placeholder={turns.length ? "Ask a follow-up" : "What are you shopping for?"}
            onSubmit={onRun}
          />
        </div>
      </aside>
    </div>
  );
}
