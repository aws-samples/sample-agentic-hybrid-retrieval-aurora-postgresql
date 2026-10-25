import {
  type CSSProperties,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
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
 * card sits below the control when 190 px fit and above it otherwise, at most 340 px
 * wide and 16 px from the edges, Escape ends the tour, and the last button reads Got
 * it. Unlike AgentEats, every click outside the card is swallowed, hole included, so a
 * participant cannot navigate away mid-tour, and a stop whose control is absent is
 * passed over (at once when optional, else after TARGET_WAIT_MS) instead of waiting
 * for it.
 *
 * The hole hugs what the participant sees, not the element's layout box: a centred
 * search field and its examples rather than the full-width row around them, and the
 * control's own corner shape, so a pill gets a pill. Between stops the hole and the
 * card travel on a critically damped spring, which can be interrupted and never
 * overshoots; once the hole arrives it locks onto the control frame by frame, so
 * scrolling or a reflow never leaves it trailing.
 *
 * A `hint` is one stop shown at a moment rather than a tour: the card reads Tip
 * with only Got it, and the page stays live, so a click on the ringed control
 * does what it says and any click closes the tip.
 */

const GAP = 14;
const EDGE = 16;
const CARD_WIDTH = 340;
const BELOW_ROOM = 190;
/** The ring and its pulse stay whole against the window's edges. */
const VIEW_INSET = 6;
/**
 * The spring's natural frequency, rad/s. Critically damped, a move across the page
 * (390 px, measured at 1440 x 900) is within half a pixel by about 0.47 s, and no
 * frame jumps more than about 50 px, where the old ease-out leapt 113 px in its first.
 */
const OMEGA = 20;
/** A move of 0.5 px and 2 px/s is finished; the hole then locks to the control. */
const SETTLED = { distance: 0.5, speed: 2 };
/** A newly shown hole closes onto its control from this much further out. */
const OPEN_FROM = 28;
/** Shop's landing renders its shelf after the header; a stop waits this long for its control. */
export const TARGET_WAIT_MS = 2_500;

type Box = { top: number; left: number; width: number; height: number; radius: number };
type Extent = { top: number; left: number; right: number; bottom: number };
type Spot = { top: number; left: number };
const BOX_KEYS = ["top", "left", "width", "height", "radius"] as const;
const SPOT_KEYS = ["top", "left"] as const;
/**
 * Elements that are one thing in themselves, whatever their styles: a control's
 * shape is its clickable box, even before hover or selection gives it a fill.
 */
const SOLID_TAGS = new Set([
  "A", "BUTTON", "INPUT", "LABEL", "SELECT", "SUMMARY", "TEXTAREA", "IMG", "SVG", "VIDEO", "CANVAS",
]);
const SOLID_ROLES = new Set(["button", "link", "tab", "menuitem", "switch", "checkbox", "radio"]);

function reducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function clamp(value: number, low: number, high: number) {
  return Math.min(Math.max(value, low), Math.max(low, high));
}

function clear(color: string): boolean {
  return color === "" || color === "transparent" || /,\s*0\)$|\/\s*0\)$/.test(color);
}

/** Whether an element draws a visible edge of its own: a fill, a border or a shadow. */
function isSolid(element: Element): boolean {
  if (SOLID_TAGS.has(element.tagName.toUpperCase())) return true;
  if (SOLID_ROLES.has(element.getAttribute("role") ?? "")) return true;
  const style = getComputedStyle(element);
  return !clear(style.backgroundColor)
    || (style.backgroundImage !== "" && style.backgroundImage !== "none")
    || (style.boxShadow !== "" && style.boxShadow !== "none")
    || (parseFloat(style.borderTopWidth) > 0 && !clear(style.borderTopColor))
    || (parseFloat(style.borderBottomWidth) > 0 && !clear(style.borderBottomColor));
}

function grow(extent: Extent | null, box: Extent): Extent {
  if (!extent) return { top: box.top, left: box.left, right: box.right, bottom: box.bottom };
  return {
    top: Math.min(extent.top, box.top),
    left: Math.min(extent.left, box.left),
    right: Math.max(extent.right, box.right),
    bottom: Math.max(extent.bottom, box.bottom),
  };
}

/**
 * The visible content of a wrapper with no edge of its own: its text, its controls and
 * its solid children, rather than the empty width a full-width row gives it.
 */
function contentExtent(element: Element, depth: number): Extent | null {
  let extent: Extent | null = null;
  for (const node of element.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!node.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const box = range.getBoundingClientRect?.();
      if (box && box.width > 0 && box.height > 0) extent = grow(extent, box);
      continue;
    }
    if (!(node instanceof Element)) continue;
    const box = node.getBoundingClientRect();
    // Skips what is not drawn, and the 1 px boxes of screen-reader-only text.
    if (box.width <= 2 || box.height <= 2 || getComputedStyle(node).visibility === "hidden") continue;
    const inner = depth < 6 && !isSolid(node) ? contentExtent(node, depth + 1) : null;
    extent = grow(extent, inner ?? box);
  }
  return extent;
}

function cornerRadius(element: Element, own: DOMRect): number {
  const style = getComputedStyle(element);
  const value = style.borderTopLeftRadius || style.borderRadius;
  const amount = parseFloat(value);
  if (Number.isNaN(amount)) return 0;
  return value.trim().endsWith("%") ? (amount / 100) * Math.min(own.width, own.height) : amount;
}

/** The hole for one control: its visible extent, padded, in its own corner shape. */
function holeAround(element: HTMLElement): Box {
  const own = element.getBoundingClientRect();
  const solid = isSolid(element);
  const seen = (solid ? null : contentExtent(element, 0)) ?? own;
  const pad = clamp(Math.round(Math.min(seen.right - seen.left, seen.bottom - seen.top) * 0.18), 6, 10);
  let top = seen.top - pad;
  let left = seen.left - pad;
  let right = seen.right + pad;
  let bottom = seen.bottom + pad;
  // A control on screen keeps its whole ring on screen; one still to scroll in is left be.
  if (seen.top >= 0) top = Math.max(top, VIEW_INSET);
  if (seen.left >= 0) left = Math.max(left, VIEW_INSET);
  if (seen.right <= window.innerWidth) right = Math.min(right, window.innerWidth - VIEW_INSET);
  if (seen.bottom <= window.innerHeight) bottom = Math.min(bottom, window.innerHeight - VIEW_INSET);
  const width = Math.max(0, right - left);
  const height = Math.max(0, bottom - top);
  const round = Math.min(width, height) / 2;
  if (!solid) return { top, left, width, height, radius: height <= 64 ? round : Math.min(16, round) };
  const corner = cornerRadius(element, own);
  const pill = corner >= Math.min(own.width, own.height) / 2 - 0.5;
  return { top, left, width, height, radius: pill ? round : Math.min(corner + pad, round) };
}

function inflate(box: Box, by: number): Box {
  return {
    top: box.top - by,
    left: box.left - by,
    width: box.width + 2 * by,
    height: box.height + 2 * by,
    radius: box.radius + by,
  };
}

function cardPlacement(hole: Box | null, cardHeight: number): Spot & { width: number } {
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

type Motion<T extends string> = { value: Record<T, number>; speed: Record<T, number> };

/**
 * One step of a critically damped spring for every key, solved exactly for the time
 * elapsed, so a slow or dropped frame never overshoots. Returns whether it settled.
 */
function spring<T extends string>(
  motion: Motion<T>, goal: Record<T, number>, keys: readonly T[], seconds: number,
): boolean {
  const decay = Math.exp(-OMEGA * seconds);
  let settled = true;
  for (const key of keys) {
    const offset = motion.value[key] - goal[key];
    const speed = motion.speed[key];
    const carry = speed + OMEGA * offset;
    const nextOffset = (offset + carry * seconds) * decay;
    const nextSpeed = (speed - OMEGA * carry * seconds) * decay;
    motion.value[key] = goal[key] + nextOffset;
    motion.speed[key] = nextSpeed;
    if (Math.abs(nextOffset) > SETTLED.distance || Math.abs(nextSpeed) > SETTLED.speed) settled = false;
  }
  if (settled) {
    for (const key of keys) {
      motion.value[key] = goal[key];
      motion.speed[key] = 0;
    }
  }
  return settled;
}

function still<T extends string>(value: Record<T, number>, keys: readonly T[]): Motion<T> {
  const speed = {} as Record<T, number>;
  for (const key of keys) speed[key] = 0;
  return { value: { ...value }, speed };
}

export function SpotlightTour(
  { open, onClose, steps = TOUR_STEPS, storageKey, hint = false }:
    { open: boolean; onClose: () => void; steps?: readonly TourStep[]; storageKey?: string; hint?: boolean },
) {
  const [index, setIndex] = useState(0);
  const [waiting, setWaiting] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const cutRef = useRef<SVGRectElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  // Where the hole and the card are now, kept across stops so each move starts from there.
  const hole = useRef<Motion<(typeof BOX_KEYS)[number]> | null>(null);
  const card = useRef<Motion<(typeof SPOT_KEYS)[number]> | null>(null);
  // A tip closed by a click elsewhere leaves focus where that click put it.
  const clickedAway = useRef(false);
  const id = useId();
  const maskId = `${id}-cut`;
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
    clickedAway.current = false;
    hole.current = null;
    card.current = null;
    setIndex(0);
    return () => {
      const previous = returnFocus.current;
      if (!clickedAway.current && previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => {
    if (!open || !hint) return undefined;
    const away = (event: PointerEvent) => {
      if (cardRef.current?.contains(event.target as Node)) return;
      clickedAway.current = true;
      end();
    };
    window.addEventListener("pointerdown", away, true);
    return () => window.removeEventListener("pointerdown", away, true);
  }, [end, hint, open]);

  /** Write the hole, its ring and the card straight to the DOM; React renders them once. */
  const draw = useCallback((box: Box | null, spot: (Spot & { width: number }) | null) => {
    const ring = ringRef.current;
    const cut = cutRef.current;
    if (ring) {
      ring.style.display = box ? "" : "none";
      if (box) {
        ring.style.top = `${box.top}px`;
        ring.style.left = `${box.left}px`;
        ring.style.width = `${box.width}px`;
        ring.style.height = `${box.height}px`;
        ring.style.borderRadius = `${box.radius}px`;
      }
    }
    if (cut) {
      cut.setAttribute("x", String(box?.left ?? 0));
      cut.setAttribute("y", String(box?.top ?? 0));
      cut.setAttribute("width", String(box?.width ?? 0));
      cut.setAttribute("height", String(box?.height ?? 0));
      cut.setAttribute("rx", String(box?.radius ?? 0));
    }
    const element = cardRef.current;
    if (element && spot) {
      element.style.width = `${spot.width}px`;
      element.style.top = `${spot.top}px`;
      element.style.left = `${spot.left}px`;
    }
  }, []);

  // Follow the control every frame: the page may scroll, the header may reflow, and
  // the shelf below Shop's search arrives after the tour starts. Until the move to
  // this stop settles the hole springs toward the control; after that it is the
  // control's own box, every frame.
  useEffect(() => {
    if (!open) return undefined;
    const target = step.target;
    const started = Date.now();
    const instant = reducedMotion();
    let last = started;
    let locked = false;
    let scrolled = false;
    let frame = 0;
    const follow = () => {
      const now = Date.now();
      const seconds = Math.min(0.064, (now - last) / 1000);
      last = now;
      const element = target === undefined ? null : visibleTarget(target);
      if (target !== undefined && !element) {
        if (step.optional || now - started > TARGET_WAIT_MS) {
          advance();
          return;
        }
        setWaiting(true);
        hole.current = null;
        draw(null, null);
        frame = requestAnimationFrame(follow);
        return;
      }
      setWaiting(false);
      if (element && !scrolled) {
        scrolled = true;
        const box = element.getBoundingClientRect();
        if (box.top < 0 || box.bottom > window.innerHeight) {
          element.scrollIntoView({ block: "center", behavior: instant ? "instant" : "smooth" });
        }
      }
      const goal = element ? holeAround(element) : null;
      const height = cardRef.current?.offsetHeight || BELOW_ROOM;
      const place = cardPlacement(goal, height);
      if (!goal) {
        hole.current = null;
      } else if (!hole.current) {
        hole.current = still(instant ? goal : inflate(goal, OPEN_FROM), BOX_KEYS);
      }
      if (!card.current) card.current = still(place, SPOT_KEYS);
      if (instant || locked) {
        if (hole.current && goal) hole.current = still(goal, BOX_KEYS);
        card.current = still(place, SPOT_KEYS);
      } else {
        const holeDone = !hole.current || !goal || spring(hole.current, goal, BOX_KEYS, seconds);
        const cardDone = spring(card.current, place, SPOT_KEYS, seconds);
        locked = holeDone && cardDone;
      }
      ringRef.current?.toggleAttribute("data-moving", !locked && !instant);
      draw(hole.current ? { ...hole.current.value } : null, { ...card.current.value, width: place.width });
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    return () => cancelAnimationFrame(frame);
  }, [advance, draw, open, step]);

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
    if (hint || event.key !== "Tab") return;
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
  // Placed once by React so the first frame is never at the corner; the loop moves it after.
  const initial: CSSProperties = cardPlacement(null, BELOW_ROOM);
  return createPortal(
    <div className="spotlight-tour">
      {hint ? null : <div className="spotlight-catcher" aria-hidden="true" />}
      {/* One scrim with the hole cut out of it: a mask redraws cheaply as the hole
          moves, where a page-sized shadow would repaint every frame. */}
      <svg className="spotlight-scrim" aria-hidden="true">
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse">
            <rect width="100%" height="100%" fill="white" />
            <rect ref={cutRef} width="0" height="0" fill="black" />
          </mask>
        </defs>
        <rect className="spotlight-dim" width="100%" height="100%" mask={`url(#${maskId})`} />
      </svg>
      <div ref={ringRef} className="spotlight-hole" style={{ display: "none" }} aria-hidden="true" />
      {waiting ? null : (
        <div
          ref={cardRef}
          className="spotlight-card"
          role="dialog"
          aria-modal={!hint}
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-body`}
          style={initial}
          onKeyDown={keepFocus}
        >
          <div key={step.id} className="spotlight-card-content">
            <p className="spotlight-count">{hint ? "Tip" : `Tour · ${index + 1} of ${steps.length}`}</p>
            <h2 id={`${id}-title`}>{step.title}</h2>
            <p id={`${id}-body`}>{step.body}</p>
            <div className="spotlight-actions">
              {hint ? null : <button type="button" className="spotlight-skip" onClick={end}>
                Skip the tour
              </button>}
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
        </div>
      )}
    </div>,
    document.body,
  );
}
