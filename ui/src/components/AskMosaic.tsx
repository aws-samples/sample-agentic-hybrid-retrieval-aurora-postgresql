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
  Search,
  Send,
  ShoppingBag,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import { cartQuantityLimit, useCommerce } from "../commerce";
import {
  formatAvailability,
  formatCategoryKey,
  formatPrice,
  formatPriceCompact,
} from "../format";
import { domainLabels, productImage } from "../media";
import {
  FINAL_LABEL,
  FUSED_LABEL,
  armLanguage,
} from "../retrievalLanguage";
import { lockBodyScroll } from "../scrollLock";
import {
  misspelledExample,
  starterExamples,
  starterPath,
  starterPathLabels,
} from "../starters";
import type {
  AgentCitation,
  AgentPartial,
  AgentPlanStep,
  AgentResponse,
  ProductSummary,
  ResultSignals,
  RetrievalExample,
  SearchFilters,
  ToolTraceStep,
} from "../types";
import { AgentRetrievalReceipt } from "./RetrievalReceipt";
import { SearchComposer } from "./SearchComposer";

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

/**
 * The concierge's four steps, named for what a shopper gets out of each one.
 *
 * They read "Interpret / Retrieve / Compare / Cite" over titles like "Intent
 * understanding" and "Cite & summarize" — a pipeline diagram in a panel a
 * shopper opens to be helped choosing headphones. Understanding, Recommendations,
 * Compare, Why these: same four steps, same four panels, same measured content.
 */
const fullRetrievalStages: Array<{
  id: AssistStage;
  label: string;
  title: string;
  description: string;
}> = [
  {
    id: "understand",
    label: "Understanding",
    title: "What I understood",
    description: "Turning your request into catalog filters.",
  },
  {
    id: "retrieve",
    label: "Recommendations",
    title: "What I found",
    description: "Searching the catalog for products with records behind them.",
  },
  {
    id: "rank",
    label: "Compare",
    title: "How they compare",
    description: "Weighing the shortlist on catalog facts, side by side.",
  },
  {
    id: "answer",
    label: "Why these",
    // Not "Why these" twice. The label sits in this card's eyebrow now, directly
    // above the title, and a step that names itself twice reads as a stutter.
    title: "What this rests on",
    description: "Naming the product records the recommendation rests on.",
  },
];

const focusedFollowUpStages: typeof fullRetrievalStages = [
  {
    id: "understand",
    label: "Understanding",
    title: "What you're asking about",
    description: "Reading your follow-up against the products I just found.",
  },
  {
    id: "rank",
    label: "Compare",
    title: "How they compare",
    description: "Reading only the records this question needs.",
  },
  {
    id: "answer",
    label: "Why these",
    title: "What this rests on",
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
    <section className="ask-mosaic-timeline" aria-label="Steps I took">
      <p className="ask-mosaic-timeline-heading">
        <GitCompareArrows size={14} aria-hidden="true" />
        Steps I took
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
              {/* The rail is the node and the connector, nothing else. The step
                  name used to sit beside the node in a 104px track, which left
                  the text 64px: "Recommendations" is one unbreakable 110px word,
                  so it overflowed and the card's own background painted over the
                  spill. Measured before the fix: client=64, scroll=110. As a card
                  eyebrow it cannot clip at any label length, and the 72px the
                  rail gave back go to the shortlist and the comparison. */}
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

/**
 * The constraints that actually ran, surfaced at the Interpret position.
 *
 * The union of `plan[].filters` across the searches the agent issued - each
 * chip is a constraint retrieval enforced against the catalog, deduplicated
 * across steps. The reference design labeled invented chips "extracted";
 * these are the extracted ones, read back from the executed plan.
 */
function Criteria({ plan }: { plan: AgentPlanStep[] }) {
  const chips = Array.from(
    new Set(plan.flatMap((step) => describeFilters(step.filters))),
  );
  if (!chips.length) return null;
  return (
    <section className="ask-mosaic-criteria">
      <h3>Filters I searched with</h3>
      <ul aria-label="Filters Mosaic searched with">
        {chips.map((chip) => (
          <li key={chip}>{chip}</li>
        ))}
      </ul>
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
 * The searches behind the shortlist, which the panel used to fetch and then
 * drop on the floor. `plan` holds one entry per search that returned
 * evidence-backed products, so this is how the request became catalog
 * constraints - the honest form of the reference design's "based on your
 * workspace and past views", which describes personalisation this system does
 * not do.
 */
function Searches({ plan }: { plan: AgentPlanStep[] }) {
  return (
    <details className="ask-mosaic-receipt ask-mosaic-search-receipt">
      <summary>
        <Search size={18} />
        How I searched
        <span>{plan.length}</span>
      </summary>
      <ol className="ask-mosaic-searches">
        {plan.map((step, index) => (
          <li key={`${index}-${step.query}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{step.query}</strong>
              <small>{step.purpose || "No filters beyond your words"}</small>
            </div>
          </li>
        ))}
      </ol>
    </details>
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
        <span>Why this one is first</span>
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
 * The recommended products, buyable.
 *
 * `recommendations` is the cited set the answer of record was written from, so
 * these are the same products the prose names - not a second, looser shortlist.
 * The bag button is the cart the rest of the store uses, so a participant can
 * finish the errand the answer started instead of reading about it.
 */
function Picks({
  products,
  imageByProductId,
  onHighlight,
  onSelectProduct,
}: {
  products: ProductSummary[];
  imageByProductId: Map<number, string>;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}) {
  const { addItem, itemQuantity } = useCommerce();
  if (!products.length) return null;
  return (
    <section className="ask-mosaic-picks" aria-label="Recommended products">
      <ol>
        {products.slice(0, 3).map((product) => {
          const inBag = itemQuantity(product.product_id);
          const limit = cartQuantityLimit(product);
          return (
            <li key={product.product_id}>
              <button
                className="ask-mosaic-pick-open"
                type="button"
                onClick={() => onSelectProduct(product.product_id)}
                onFocus={() => onHighlight(product.product_id)}
                onBlur={() => onHighlight(null)}
                onMouseEnter={() => onHighlight(product.product_id)}
                onMouseLeave={() => onHighlight(null)}
              >
                <img
                  src={imageByProductId.get(product.product_id) ?? productImage(product)}
                  alt=""
                  width={1200}
                  height={800}
                  loading="lazy"
                  decoding="async"
                />
                <span>
                  <strong>{product.brand} {product.model}</strong>
                  <small>{formatCategoryKey(product.category_key)}</small>
                </span>
              </button>
              <span className="ask-mosaic-pick-meta">
                <strong>{formatPrice(product.price_cents, product.currency)}</strong>
                <small>{formatAvailability(product.availability)}</small>
              </span>
              <button
                className={inBag ? "ask-mosaic-pick-add in-bag" : "ask-mosaic-pick-add"}
                type="button"
                disabled={!limit || inBag >= limit}
                title={limit ? undefined : "Out of stock"}
                onClick={() => addItem(product)}
              >
                <ShoppingBag size={14} aria-hidden="true" />
                {inBag ? `In bag (${inBag})` : "Add to bag"}
              </button>
            </li>
          );
        })}
      </ol>
    </section>
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

/**
 * Cuts the reveal back to the last point that renders cleanly as Markdown.
 *
 * A slice that stops between a bold marker and its close would paint literal
 * asterisks for a few frames. Holding the reveal just before the opener means
 * an emphasized phrase appears whole once its closing marker has streamed in.
 */
function balancedMarkdownSlice(text: string, length: number): string {
  if (length >= text.length) return text;
  const slice = text.slice(0, length);
  const boldMarks = slice.split("**").length - 1;
  if (boldMarks % 2 === 0) return slice;
  return slice.slice(0, slice.lastIndexOf("**"));
}

interface TypewriterReveal {
  /** The prose typed so far; the full text once the reveal has caught up. */
  text: string;
  done: boolean;
}

/**
 * Paces streamed prose into a left-to-right typewriter reveal.
 *
 * The service delivers the answer in three-word chunks, and painting each chunk
 * the moment it lands makes the paragraph pop and reflow rather than write.
 * This advances a few characters per animation frame instead, speeding up with
 * the backlog so it trails the live stream by well under a second, then types
 * the tail out after the stream closes. A turn that mounts already answered —
 * reopening the panel, revisiting history — renders whole, as does everything
 * under reduced motion.
 */
function useTypewriterReveal(
  text: string,
  streaming: boolean,
  enabled: boolean,
  instant: boolean,
): TypewriterReveal {
  const [startedStreaming] = useState(streaming);
  const [revealedCount, setRevealedCount] = useState(0);
  const pace = enabled && startedStreaming && !instant;
  const done = !pace || revealedCount >= text.length;
  useEffect(() => {
    if (done) return undefined;
    let frame = window.requestAnimationFrame(function step() {
      setRevealedCount((current) => {
        const backlog = text.length - current;
        if (backlog <= 0) return current;
        if (backlog > 240) return current + 14;
        if (backlog > 60) return current + 8;
        return current + 3;
      });
      frame = window.requestAnimationFrame(step);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [done, text]);
  if (!enabled) return { text: "", done: false };
  if (!pace) return { text, done: true };
  return { text: balancedMarkdownSlice(text, revealedCount), done };
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
  const comparison = candidates.length > 1
    ? (
      <>
        <CompareMatrix candidates={candidates} />
        <Ranking candidates={candidates} />
      </>
    )
    : null;
  const stagePanels: Partial<Record<AssistStage, ReactNode>> = {
    understand: plan.length ? <Criteria plan={plan} /> : null,
    retrieve: candidates.length
      ? (
        <>
          <Shortlist
            candidates={candidates}
            imageByProductId={imageByProductId}
            highlightedProductId={highlightedProductId}
            onHighlight={onHighlight}
            onSelectProduct={onSelectProduct}
          />
          {plan.length ? <Searches plan={plan} /> : null}
        </>
      )
      : null,
    rank: comparison,
    answer: citations.length || trace.length
      ? (
        <>
          {citations.length ? <Evidence citations={citations} /> : null}
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
            {/* The wrapper bounds the caret: the shortlist below is part of the
                same section, and a section-level `:last-child` put the caret
                after the product cards instead of the prose being written. */}
            <div className="ask-mosaic-prose">
              <Markdown>
                {boldRecommendationNames(reveal.text, response.recommendations)}
              </Markdown>
            </div>
            {/* A fail-closed run is a fact about this answer, and an absent badge
                does not state it. */}
            {answerSettled && !response.citations.length ? (
              <p className="ask-mosaic-uncited-note">
                No product record backs this answer, so read it as a suggestion
                rather than a checked recommendation. Ask again, or add a detail
                such as a budget or a category.
              </p>
            ) : null}
            {/* The prose named these products. Here they are, priced and
                buyable, so the recommendation ends in the store rather than in
                a paragraph. */}
            <AnimatePresence initial={false}>
              {answerSettled ? (
                <motion.div
                  initial={{ opacity: 0, transform: "translateY(6px)" }}
                  animate={{ opacity: 1, transform: "translateY(0)" }}
                  transition={{
                    duration: reduceMotion ? 0 : 0.22,
                    ease: [0.23, 1, 0.32, 1],
                  }}
                >
                  <Picks
                    products={response.recommendations}
                    imageByProductId={imageByProductId}
                    onHighlight={onHighlight}
                    onSelectProduct={onSelectProduct}
                  />
                </motion.div>
              ) : null}
            </AnimatePresence>
          </section>

          {answerSettled ? (
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

/**
 * One card per retrieval arm, so the entry state shows the contrast the
 * workshop teaches before anyone types: the same catalog answers exact terms
 * and meaning, both on click, and a misspelling by filling a box rather than
 * pressing one.
 * The eval metadata stays behind the surface; shoppers see useful questions,
 * while the run itself reports what actually happened.
 */
function EntryState({
  examples,
  onRun,
  onSeed,
}: {
  /** The eval set, unfiltered. Both selectors below read it. */
  examples: RetrievalExample[];
  onRun: (query: string) => void;
  /** Puts a query in the composer without sending it. */
  onSeed: (query: string) => void;
}) {
  const starters = starterExamples(examples);
  /**
   * The close-spelling path, offered as a box to fill rather than a question to
   * press.
   *
   * The other two `starters` run on click, and this one deliberately does not.
   * Its query is misspelled on purpose - it is how the eval set exercises the
   * trigram arm - and a card that printed it would ship a spelling mistake as
   * the store's own suggestion. Loading it into the composer instead leaves the
   * typo where the lesson needs it: in the shopper's input, sent by the
   * shopper. Mosaic does not manufacture the typo. Mosaic handles it.
   */
  const fuzzy = misspelledExample(examples);
  return (
    <section className="ask-mosaic-empty">
      {starters.length ? (
        <div className="ask-mosaic-starters">
          <h4>Try asking</h4>
          <ul aria-label="Example questions">
            {starters.map((starter) => (
              <li key={starter.query_id}>
                <button
                  type="button"
                  aria-label={starter.query}
                  onClick={() => onRun(starter.query)}
                >
                  <span className="ask-mosaic-starter-path">
                    {starterPathLabels[starterPath(starter)]}
                  </span>
                  <ArrowUpRight
                    className="ask-mosaic-starter-go"
                    size={14}
                    aria-hidden="true"
                  />
                  <span className="ask-mosaic-starter-query">
                    {starter.query}
                  </span>
                </button>
              </li>
            ))}
            {fuzzy ? (
              <li key={fuzzy.query_id}>
                <button
                  className="ask-mosaic-starter-seed"
                  type="button"
                  aria-label="Put a misspelled search in the box, ready to send"
                  onClick={() => onSeed(fuzzy.query)}
                >
                  <span className="ask-mosaic-starter-path">
                    {starterPathLabels.misspelled}
                  </span>
                  <PencilLine
                    className="ask-mosaic-starter-go"
                    size={14}
                    aria-hidden="true"
                  />
                  <span className="ask-mosaic-starter-query">
                    Search with typos in it
                  </span>
                  <span className="ask-mosaic-starter-hint">
                    Fills the box. You send it.
                  </span>
                </button>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      <details className="ask-mosaic-capability">
        <summary>
          <span>
            <strong>What I can do</strong>
            <small>Five things, and you can see each one run</small>
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
  /**
   * The eval set the entry state draws its examples from. Empty if the fetch
   * failed, which is why the entry state treats them as optional.
   */
  examples: RetrievalExample[];
  /** Photographs the Shop grid assigned, so the rail agrees with the cards. */
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onClose: () => void;
  /** Discards the conversation and leaves the panel open on the entry state. */
  onClear: () => void;
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
  examples,
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
              <p>A concierge that shows its work</p>
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
              examples={examples}
              onRun={onRun}
              onSeed={editRequest}
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
              aria-label="Your preferences, passed to Ask Mosaic"
            >
              <span>Your preferences</span>
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
