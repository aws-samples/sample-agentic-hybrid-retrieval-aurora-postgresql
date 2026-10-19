/**
 * Mosaic's guided tour: the stops a participant opening the app for the first time
 * needs, in the order the header and Shop's landing put them on screen.
 *
 * Each stop names its element by a `data-tour` attribute, so a restyle cannot move
 * the spotlight to the wrong control. A stop whose element is not on screen is passed
 * over rather than shown pointing at nothing: at once when it is optional, otherwise
 * after waiting briefly for content that renders late.
 */
export interface TourStep {
  id: string;
  /** The `data-tour` value of the element to spotlight; none centres the card. */
  target?: string;
  /**
   * Passed over at once when its control is absent, instead of waiting for it: the
   * Code Editor link is not rendered without a Code Editor URL, and Playground folds
   * into the menu on narrow screens.
   */
  optional?: boolean;
  title: string;
  body: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    title: "Welcome to Mosaic",
    body: "A store searched by Amazon Aurora PostgreSQL: your labs run in the terminal, "
      + "and Mosaic shows the same results.",
  },
  {
    id: "search",
    target: "search",
    title: "Search like a shopper",
    body: "Type a request or pick an example. After a search, the strip above the "
      + "results shows how it ran, each result shows which searches found it, and "
      + "Search details has the full record.",
  },
  {
    id: "browse",
    target: "browse",
    title: "Browse and filter",
    body: "Browse all products opens the whole catalog, with the domain tabs and the "
      + "Category menu.",
  },
  {
    id: "ask",
    target: "ask",
    title: "Ask the Retrieval agent",
    body: "Ask Mosaic is the Retrieval agent you build in Lab 3, citing a source for "
      + "every claim.",
  },
  {
    id: "playground",
    target: "playground",
    optional: true,
    title: "See every step of a search",
    body: "Playground replays a search: the three lists, how they combine and what "
      + "reranking changed.",
  },
  {
    id: "alex",
    target: "alex",
    title: "Meet Alex",
    body: "Alex's brief: the headphones, monitor and chair his home office still needs.",
  },
  {
    id: "code-editor",
    target: "code-editor",
    optional: true,
    title: "Back to your labs",
    body: "Every lab runs in Code Editor's terminal, which this opens in a new tab.",
  },
];

export const TOUR_STORAGE_KEY = "mosaic-tour";
/** Bump the suffix when the stops change enough that returning viewers should see them. */
export const TOUR_SEEN = "seen-v1";

/** Storage is a per-browser convenience: unavailable storage means "not seen yet". */
export function hasSeenTour(): boolean {
  try {
    return window.localStorage.getItem(TOUR_STORAGE_KEY) === TOUR_SEEN;
  } catch {
    return false;
  }
}

export function markTourSeen(): void {
  try {
    window.localStorage.setItem(TOUR_STORAGE_KEY, TOUR_SEEN);
  } catch {
    // A private window keeps no storage; the tour then simply offers itself again.
  }
}

/** The element a step spotlights, when it is rendered and has a size on screen. */
export function visibleTarget(target: string): HTMLElement | null {
  const element = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
  if (!element || element.getClientRects().length === 0) return null;
  const box = element.getBoundingClientRect();
  if (box.width === 0 || box.height === 0) return null;
  return getComputedStyle(element).visibility === "hidden" ? null : element;
}
