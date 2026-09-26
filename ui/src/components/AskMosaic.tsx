import { DeclinedAnswer } from "./DeclinedAnswer";
import { MemoryControl, MemoryReceipt, type AskMosaicMemoryControl } from "./AskMosaicMemory";
import {
  ChevronDown,
  CircleCheck,
  CircleStop,
  Eraser,
  LoaderCircle,
  PencilLine,
  RotateCcw,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { lockBodyScroll } from "../scrollLock";
import { useTypewriterReveal } from "../useTypewriterReveal";
import type { mosaicLabManifest } from "../labMissions";
import type {
  AgentCitation,
  AgentPlanStep,
  ProductSummary,
  SearchFilters,
  ToolTraceStep,
} from "../types";
import { Criteria, Searches } from "./agentAnswerParts";
import { AgentRetrievalReceipt } from "./RetrievalReceipt";
import { SearchComposer } from "./SearchComposer";
import { ProductAnswer } from "./ProductAnswer";
import {
  CompareMatrix,
  Evidence,
  Activity,
  Ranking,
  Shortlist,
} from "./ask-mosaic/EvidencePanels";
import { FollowUps, ShoppingResultCard } from "./ask-mosaic/ResultCards";
import { StageRail, useProgressiveStage } from "./ask-mosaic/StageProgress";
import {
  focusedFollowUpStages,
  fullRetrievalStages,
  type AskMosaicTurn,
  type AssistStage,
} from "./ask-mosaic/types";

export type { AskMosaicTurn } from "./ask-mosaic/types";

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

/**
 * One exchange, end to end: the question, its retrieval progress, and the
 * cited answer once it arrives.
 *
 * This is the conversation's orchestrator. `StageProgress`, `EvidencePanels`,
 * and `ResultCards` supply the presentation for each of a turn's stages; this
 * component owns the state transitions between them (streaming, settled,
 * declined, cancelled, failed) and hands each stage only the props it needs.
 */
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

      {turn.loading || turn.stage || response || turn.cancelled ? (
        <details
          className="ask-mosaic-process"
          open={!answerVisible || Boolean(turn.error) || turn.cancelled}
        >
          <summary>
            <span>
              {turn.error
                ? "Request details"
                : turn.cancelled
                  ? "Stopped"
                  : answerVisible ? "Steps and sources" : "Search in progress"}
            </span>
            <small>
              {turn.error
                ? "Request interrupted"
                : turn.cancelled
                  ? "Generation stopped before it finished"
                  : answerVisible ? "Inspect what Mosaic used" : presentedStageTitle}
            </small>
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
        <StageRail
          actualStage={actualStage}
          cancelled={turn.cancelled}
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

      {turn.cancelled ? (
        <div className="ask-mosaic-cancelled" role="status">
          <span className="ask-mosaic-cancelled-heading">
            <CircleStop size={15} aria-hidden="true" />
            You stopped this request.
          </span>
          {turn.streamed
            ? <small>The partial answer and steps above are what Mosaic had found so far.</small>
            : <small>Ask again, or send a new request.</small>}
        </div>
      ) : null}

      {turn.error ? (
        <div className="ask-mosaic-error" role="alert">
          <strong>Mosaic could not finish this request.</strong>
          <span>{turn.error}</span>
          <small>Press Ask again to retry. If it keeps failing, share this message with your facilitator.</small>
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
              <DeclinedAnswer answer={reveal.text} reason={response.decline_reason} className="ask-mosaic-declined" />
            ) : (
              <>
                <p>
                  <Sparkles size={14} />
                  {answerSettled
                    ? "Final recommendation"
                    : turn.cancelled ? "Partial answer" : "Writing the answer"}
                  {!reveal.done && reveal.text ? (
                    <button type="button" className="ask-mosaic-skip-reveal" onClick={reveal.skip}>
                      Show the full answer
                    </button>
                  ) : null}
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

          {answerSettled ? <MemoryReceipt memory={response.memory} /> : null}
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
      <h3>What can I help you find?</h3>
      <p>{suggestions.length
        ? "Choose a starting point, or tell me what matters to you."
        : "Tell me what matters to you. I’ll help you compare the options."}</p>
    </div>
    {suggestions.length ? <div className="ask-mosaic-starters">
      <ul aria-label="Example questions">{suggestions.map((suggestion) => <li key={suggestion.id}>
        <button type="button" onClick={() => onRun(suggestion.query, suggestion.filters)}>
          <span className="ask-mosaic-starter-path">{suggestion.shop_label}</span>
        </button>
      </li>)}</ul>
    </div> : null}
  </section>;
}

interface AskMosaicProps {
  memory?: AskMosaicMemoryControl;
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
  /** Stops the turn in progress; the conversation and its partial results stay. */
  onStop: () => void;
  onRun: (query: string, filters?: SearchFilters) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

/**
 * The sidecar shell: modal/complementary framing, focus management, scroll
 * following, and the composer. `Turn` and `EntryState` supply the content;
 * this component owns nothing about how a turn renders.
 */
export function AskMosaic({
  memory,
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
  onStop,
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
  /**
   * Mirrors `followTailRef` for rendering. The ref alone drives the actual
   * auto-follow decision inside `handleThreadScroll`/`followReveal` because a
   * ref update must not itself trigger a render on every scroll tick; this
   * state exists only to show or hide the "Jump to latest" control.
   */
  const [nearBottom, setNearBottom] = useState(true);
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
    const atBottom = (
      thread.scrollHeight - thread.scrollTop - thread.clientHeight
    ) <= 48;
    followTailRef.current = atBottom;
    setNearBottom(atBottom);
  }, []);

  /**
   * Return to the live edge without taking keyboard focus. A reader who
   * scrolled up to read earlier text presses this deliberately; moving focus
   * would additionally jump the visible viewport on a narrow screen and
   * interrupt whatever they were doing with the keyboard.
   */
  const jumpToLatest = useCallback(() => {
    followTailRef.current = true;
    setNearBottom(true);
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, []);

  /** A newly opened conversation or a question the reader just sent owns focus. */
  useEffect(() => {
    if (!open) return;
    followTailRef.current = true;
    setNearBottom(true);
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
              <p>A little help choosing.</p>
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

        <div className="ask-mosaic-body-wrap">
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
          {/* Only once a reader has actually scrolled away from the live edge,
              and only while there is a live edge worth returning to. Auto-follow
              in `followReveal` already keeps the writing line in view; this is
              the way back after a reader chose to read something above it. */}
          {!nearBottom && turns.length ? (
            <button
              className="ask-mosaic-jump-latest"
              type="button"
              onClick={jumpToLatest}
            >
              <ChevronDown size={14} aria-hidden="true" />
              Jump to latest
            </button>
          ) : null}
        </div>

        {/* Pinned under the thread, where a conversation puts it. It used to sit
            above the answer, so the reply to a question appeared below the field
            that would replace it. */}
        <div className="ask-mosaic-composer">
          {memory ? <MemoryControl memory={memory} pending={pending} /> : null}
          {contextFilters.length ? (
            <div
              className="ask-mosaic-context"
              aria-label="Current search filters, passed to Ask Mosaic"
            >
              <span>Search filters</span>
              <strong>{contextFilters.join(" · ")}</strong>
            </div>
          ) : null}
          {pending ? (
            <div className="ask-mosaic-generating" role="status">
              <span>
                <LoaderCircle className="spin" size={14} aria-hidden="true" />
                Working on your request
              </span>
              <button className="ask-mosaic-stop" type="button" onClick={onStop}>
                <CircleStop size={15} aria-hidden="true" />
                Stop generating
              </button>
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
