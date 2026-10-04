import { MemoryControl, type AskMosaicMemoryControl } from "./AskMosaicMemory";
import {
  ChevronDown,
  CircleStop,
  Eraser,
  LoaderCircle,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { lockBodyScroll } from "../scrollLock";
import type { workspaceRequests } from "../labMissions";
import type { SearchFilters } from "../types";
import { SearchComposer } from "./SearchComposer";
import { useBuilderView } from "./ask-mosaic/useBuilderView";
import { StarterCards } from "./ask-mosaic/StarterCards";
import { Turn } from "./ask-mosaic/Turn";
import type { AskMosaicTurn } from "./ask-mosaic/types";

export type { AskMosaicTurn } from "./ask-mosaic/types";

type WorkspaceRequest = ReturnType<typeof workspaceRequests>[number];


interface AskMosaicProps {
  memory?: AskMosaicMemoryControl;
  open: boolean;
  /** What the composer starts with. The Shop query on a cold open. */
  seedQuery: string;
  /** Active Shop filters passed to every agent request. */
  contextFilters: string[];
  /** A one-line fact about how the last request was sent, shown above the composer. */
  notice?: string;
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
  /** `replaceShopFilters` is set for a lab starter, which runs on its own filters. */
  onRun: (query: string, filters?: SearchFilters, replaceShopFilters?: boolean) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

/**
 * The sidecar shell: modal/complementary framing, focus management, scroll
 * following, and the composer. `Turn` and `StarterCards` supply the content;
 * this component owns nothing about how a turn renders.
 */
export function AskMosaic({
  memory,
  open,
  seedQuery,
  contextFilters,
  notice,
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
  const hasTurns = latest !== null;
  const [builder, setBuilder] = useBuilderView();

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
    // The starters read from their heading down, so an empty thread starts at the top.
    const frame = window.requestAnimationFrame(() => {
      const thread = threadRef.current;
      if (thread && !hasTurns) thread.scrollTop = 0;
      else followReveal();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, latest?.id, hasTurns, followReveal]);

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
          <span className="ask-mosaic-mark" aria-hidden="true"><Sparkles size={16} /></span>
          <div className="ask-mosaic-heading">
            <h2 id="ask-mosaic-title">Ask Mosaic</h2>
            <p>Answers from the catalog, with sources</p>
          </div>
          <button
            className="ask-switch"
            type="button"
            role="switch"
            aria-checked={builder}
            onClick={() => setBuilder(!builder)}
          >
            Builder view
            <span className="ask-switch-track" aria-hidden="true"><span className="ask-switch-knob" /></span>
          </button>
          {/* Only once there is something to discard. On the entry state the
              control would clear nothing, and it would sit beside the starters
              it appears to threaten. */}
          {turns.length ? (
            <button
              className="ask-icon-button"
              type="button"
              aria-label="Clear chat"
              title="Clear chat"
              onClick={onClear}
            >
              <Eraser size={14} aria-hidden="true" />
            </button>
          ) : null}
          <button
            className="ask-icon-button ask-mosaic-header-close"
            type="button"
            aria-label="Close Ask Mosaic"
            onClick={onClose}
          >
            <X size={14} aria-hidden="true" />
          </button>
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
                  builder={builder}
                  onRun={onRun}
                  onEdit={editRequest}
                  onHighlight={onHighlight}
                  onSelectProduct={onSelectProduct}
                  priorQuestions={turns.slice(0, index).map((earlier) => earlier.question)}
                  previousBestPickId={
                    turns.slice(0, index).reverse()
                      .find((earlier) => earlier.response?.recommendations.length)
                      ?.response?.recommendations[0].product_id ?? null
                  }
                  onStageProgress={index === turns.length - 1 ? followReveal : undefined}
                  onRevealProgress={index === turns.length - 1 ? followReveal : undefined}
                />
              ))
            ) : (
              <StarterCards suggestions={suggestions} onRun={onRun} />
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
          {notice ? <p className="ask-mosaic-notice" role="status">{notice}</p> : null}
          {contextFilters.length ? (
            <div
              className="ask-mosaic-context"
              aria-label="Current search filters, passed to Ask Mosaic"
            >
              <span>Search filters</span>
              {contextFilters.map((filter) => <strong key={filter}>{filter}</strong>)}
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
