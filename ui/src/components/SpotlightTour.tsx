import {
  type CSSProperties,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { markTourSeen, TOUR_STEPS, type TourStep, visibleTarget } from "../tour";
import "../spotlight-tour.css";

/**
 * The guided tour: a dimmed page with a hole and a pulsing ring around one control,
 * and a card saying what it is, with Next and Skip the tour.
 *
 * It follows the AgentEats (DAT432) spotlight so the two workshops behave alike: the
 * hole is the control's box plus 8 px, the card sits below it when 190 px fit and above
 * it otherwise, at most 340 px wide and 16 px from the edges, Escape ends the tour, and
 * the last button reads Got it. Unlike AgentEats, every click outside the card is
 * swallowed, hole included, so a participant cannot navigate away mid-tour, and a stop
 * whose control is absent is passed over (at once when optional, else after
 * TARGET_WAIT_MS) instead of waiting for it.
 */

const HOLE_PAD = 8;
const GAP = 14;
const EDGE = 16;
const CARD_WIDTH = 340;
const BELOW_ROOM = 190;
/** Shop's landing renders its shelf after the header; a stop waits this long for its control. */
export const TARGET_WAIT_MS = 2_500;

type Hole = { top: number; left: number; width: number; height: number };

function reducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function holeAround(element: HTMLElement): Hole {
  const box = element.getBoundingClientRect();
  return {
    top: box.top - HOLE_PAD,
    left: box.left - HOLE_PAD,
    width: box.width + 2 * HOLE_PAD,
    height: box.height + 2 * HOLE_PAD,
  };
}

function sameHole(a: Hole | null, b: Hole): boolean {
  return a !== null && a.top === b.top && a.left === b.left
    && a.width === b.width && a.height === b.height;
}

function offScreen(element: HTMLElement): boolean {
  const box = element.getBoundingClientRect();
  return box.top < 0 || box.bottom > window.innerHeight;
}

function clamp(value: number, low: number, high: number) {
  return Math.min(Math.max(value, low), Math.max(low, high));
}

function cardPlacement(hole: Hole | null, cardHeight: number): CSSProperties {
  const width = Math.min(CARD_WIDTH, window.innerWidth - 2 * EDGE);
  if (!hole) {
    return {
      width,
      left: (window.innerWidth - width) / 2,
      top: Math.max(EDGE, (window.innerHeight - cardHeight) / 2),
    };
  }
  const centred = hole.left + hole.width / 2 - width / 2;
  const left = clamp(centred, EDGE, window.innerWidth - width - EDGE);
  const below = hole.top + hole.height + GAP;
  const top = window.innerHeight - EDGE - below >= Math.max(BELOW_ROOM, cardHeight)
    ? below
    : Math.max(EDGE, hole.top - GAP - cardHeight);
  return { width, left, top };
}

export function SpotlightTour(
  { open, onClose, steps = TOUR_STEPS, storageKey }:
    { open: boolean; onClose: () => void; steps?: TourStep[]; storageKey?: string },
) {
  const [index, setIndex] = useState(0);
  const [hole, setHole] = useState<Hole | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [cardHeight, setCardHeight] = useState(BELOW_ROOM);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const id = useId();
  const step = steps[Math.min(index, steps.length - 1)];
  // Only optional stops can be known not to come, so only they make this the last one.
  const lastShown = steps.slice(index + 1).every((later) => later.optional === true
    && later.target !== undefined && visibleTarget(later.target) === null);

  const end = useCallback(() => {
    markTourSeen(storageKey);
    onClose();
  }, [onClose, storageKey]);

  const advance = useCallback(() => {
    if (index >= steps.length - 1) end();
    else setIndex(index + 1);
  }, [end, index, steps.length]);

  useEffect(() => {
    if (!open) return undefined;
    const active = document.activeElement;
    returnFocus.current = active instanceof HTMLElement ? active : null;
    setIndex(0);
    return () => {
      const previous = returnFocus.current;
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);

  // Follow the control every frame: the page may scroll, the header may reflow, and
  // the shelf below Shop's search arrives after the tour starts. The DOM is touched
  // only when the hole actually moves.
  useEffect(() => {
    if (!open) return undefined;
    const target = step.target;
    if (target === undefined) {
      setHole(null);
      setWaiting(false);
      return undefined;
    }
    const started = Date.now();
    let scrolled = false;
    let frame = 0;
    const follow = () => {
      const element = visibleTarget(target);
      if (!element) {
        if (step.optional || Date.now() - started > TARGET_WAIT_MS) {
          advance();
          return;
        }
        setWaiting(true);
        frame = requestAnimationFrame(follow);
        return;
      }
      if (!scrolled) {
        scrolled = true;
        if (offScreen(element)) {
          const behavior = reducedMotion() ? "instant" : "smooth";
          element.scrollIntoView({ block: "center", behavior });
        }
      }
      setWaiting(false);
      const next = holeAround(element);
      setHole((current) => (sameHole(current, next) ? current : next));
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    return () => cancelAnimationFrame(frame);
  }, [advance, open, step]);

  useLayoutEffect(() => {
    const height = cardRef.current?.offsetHeight;
    if (height && height !== cardHeight) setCardHeight(height);
  });

  useEffect(() => {
    if (open && !waiting) nextRef.current?.focus({ preventScroll: true });
  }, [index, open, waiting]);

  useEffect(() => {
    if (!open) return undefined;
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      end();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [end, open]);

  /** Tab stays on the card's two buttons while the tour is open. */
  const keepFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const found = cardRef.current?.querySelectorAll<HTMLButtonElement>("button");
    const buttons = [...(found ?? [])];
    if (buttons.length === 0) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  if (!open) return null;
  return createPortal(
    <div className="spotlight-tour">
      <div className="spotlight-catcher" aria-hidden="true" />
      {hole && !waiting ? (
        <div className="spotlight-hole" style={hole} aria-hidden="true" />
      ) : (
        <div className="spotlight-scrim" aria-hidden="true" />
      )}
      {waiting ? null : (
        <div
          ref={cardRef}
          className="spotlight-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-body`}
          style={cardPlacement(hole, cardHeight)}
          onKeyDown={keepFocus}
        >
          <p className="spotlight-count">Tour · {index + 1} of {steps.length}</p>
          <h2 id={`${id}-title`}>{step.title}</h2>
          <p id={`${id}-body`}>{step.body}</p>
          <div className="spotlight-actions">
            <button type="button" className="spotlight-skip" onClick={end}>
              Skip the tour
            </button>
            <button
              ref={nextRef}
              type="button"
              className="spotlight-next"
              onClick={lastShown ? end : advance}
            >
              {lastShown ? "Got it" : "Next"}
            </button>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
