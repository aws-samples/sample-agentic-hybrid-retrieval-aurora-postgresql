import {
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LoaderCircle,
  Search,
  Send,
  Sparkles,
  Star,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "motion/react";
import {
  CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { Link } from "wouter";
import { api } from "../api";
import { AskMosaic } from "../components/AskMosaic";
import {
  CatalogSearchComposer,
  catalogGhostQueries,
} from "../components/CatalogSearchComposer";
import { CodeEditorLink } from "../components/CodeEditorLink";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { ProductCard } from "../components/ProductCard";
import { ProductDrawer } from "../components/ProductDrawer";
import { SearchRetrievalReceipt } from "../components/RetrievalReceipt";
import { useAskMosaicConversation } from "../components/useAskMosaicConversation";
import { productImageMap } from "../media";
import { CatalogLoadingState, ErrorState } from "../components/States";
import {
  formatAvailability,
  formatCategoryKey,
} from "../format";
import {
  agentLabOutcome,
  retrievalLabOutcome,
  runMatchesMissionGates,
  type LabOutcome,
} from "../labOutcome";
import {
  coreMosaicLabs,
  mosaicRetrievalExamples,
  type MosaicLabMission,
} from "../labMissions";
import {
  RETRIEVAL_SURFACE,
  playgroundQueryHref,
  useSearchParams,
} from "../navigation";
import { lockBodyScroll } from "../scrollLock";
import type {
  Availability,
  CatalogPage,
  Domain,
  ProductSummary,
  ReadinessResponse,
  SearchFilters,
  SearchResponse,
} from "../types";

const pageSize = 12;
const priceCeiling = 2000;
const priceStep = 25;
const priceCeilingCents = priceCeiling * 100;
const ratingThresholds = [5, 4, 3, 2, 1] as const;
const EASE_OUT = [0.16, 1, 0.3, 1] as const;

const domainOptions: Array<{ value?: Domain; label: string }> = [
  { label: "All products" },
  { value: "consumer_electronics", label: "Electronics" },
  { value: "running_fitness", label: "Running & fitness" },
  { value: "home_office", label: "Workspace" },
];

const domainLabels: Record<Domain, string> = {
  consumer_electronics: "Electronics",
  running_fitness: "Running & fitness",
  home_office: "Workspace",
};

const availabilityOptions: Array<{ value: Availability | ""; label: string }> = [
  { value: "", label: "All availability" },
  { value: "in_stock", label: "In stock" },
  { value: "low_stock", label: "Low stock" },
  { value: "preorder", label: "Pre-order" },
];

type FilterSection = "categories" | "brand" | "price" | "availability" | "rating";

function priceFromCents(value: string | null, fallback: number) {
  if (value === null) return fallback;
  const cents = Number(value);
  if (!Number.isFinite(cents)) return fallback;
  return Math.min(Math.max(cents / 100, 0), priceCeiling);
}

function mergeVisibleProducts(
  recommendations: ProductSummary[] | null,
  products: ProductSummary[],
) {
  if (!recommendations?.length) return products;
  const recommendationIds = new Set(
    recommendations.map((product) => product.product_id),
  );
  return [
    ...recommendations,
    ...products.filter((product) => !recommendationIds.has(product.product_id)),
  ].slice(0, pageSize);
}

/**
 * Which request a `view=results` hand-off identifies, for the scroll that runs
 * once per hand-off. `event` records the run the response produced rather than
 * the request that was made, so recording it must not read as a second hand-off
 * and scroll the shopper down a second time.
 */
function resultsViewKey(search: string): string {
  const params = new URLSearchParams(search);
  params.delete("event");
  return params.toString();
}

/**
 * Which retrieval request a response is an answer to.
 *
 * The served run is recorded on Shop's own URL, so it has to be retired the
 * moment the request changes rather than when the next response lands. In
 * between, the URL said `?q=B&event=<the run that answered A>`, and the
 * Playground took delivery of that link and asserted "This is the exact run
 * from Shop" over a query that run never saw.
 *
 * Both sides of the comparison are render-time values, which is the point: an
 * effect testing `retrievalLoading` reads the value from the render before the
 * one that changed the request, so it records the stale run anyway.
 */
function retrievalRequestKey(query: string, filters: SearchFilters): string {
  return JSON.stringify([query, filters]);
}

/**
 * The lab whose defect a shopper can walk into without being told.
 *
 * Lab 1's fault has no other symptom. The trigram channel is disconnected, so a
 * misspelled query returns a page of plausible headphones with the one product
 * it is about missing from it, and nothing on the page says so. Every other
 * surface in the workshop teaches this by asking the participant to go and look;
 * Shop has to say it where the failure happens.
 */
const retrievalLab = coreMosaicLabs.find(
  (mission) => mission.stage === "retrieve" && mission.participant_edit,
);

/**
 * The one product Lab 1 is about, named rather than looked up.
 *
 * A product that never came back carries no title, so the absent case has no
 * response field to read it from. `mosaic_labs_missions.json` pins the mission
 * to `target_product_ids: [2]`, and this is that product.
 *
 * Re-point the mission and `namesTheTarget` below stops matching, so the heading
 * falls back to the outcome's own title rather than naming a product the run was
 * never about. The name is printed only while the manifest still agrees with it;
 * it is never printed wrongly.
 */
const RETRIEVAL_LAB_TARGET = { product_id: 2, name: "Sonora WH-C720" } as const;

/** Lab 1, by position in the manifest rather than by a number written twice. */
const retrievalLabNumber = coreMosaicLabs.findIndex(
  (mission) => mission === retrievalLab,
) + 1;

interface RetrievalLabCallout {
  mission: MosaicLabMission;
  outcome: LabOutcome;
  targetPresent: boolean;
  repaired: boolean;
  /**
   * Whether readiness says the environment, not the lab, is what is wrong.
   *
   * A missing trigram index and an unrepaired CTE produce the same evidence: no
   * candidate carries a trigram rank and the target is gone. Sending a
   * participant to edit SQL that was never the problem costs them the lab.
   */
  blocked: boolean;
  /** The heading for the absent case, which names a product the response cannot. */
  missingHeading: string;
}

/**
 * Whether this run is Lab 1's own request, and what it says about the repair.
 *
 * Keyed on the run rather than on `?mission=`, so a participant who typed the
 * misspelled query themselves meets the same callout as one who arrived from the
 * hero chip. Both the words and the gates have to match: the same words under
 * wider gates retrieved a different pool, and grading that would report a defect
 * the run never exercised.
 *
 * `targetPresent` and the outcome answer different questions and both are
 * needed. A target that is absent is the fault a participant can see. A target
 * that came back without a trigram rank is a repair that has not landed yet, and
 * calling that "verified" over the top of it would be the workshop lying about
 * its own checkpoint.
 *
 * `readiness` is what separates the third case from the first two. Without it
 * `retrievalLabOutcome` can only report `broken`, and this callout then told a
 * participant whose trigram index is missing, or whose corpus never seeded, that
 * they were looking at Lab 1's deliberate fault and should go and edit the SQL.
 * The Playground has read readiness before grading since it was built; Shop is
 * the surface a participant meets first and it was grading without it.
 */
function retrievalLabCallout(
  response: SearchResponse | null,
  readiness: ReadinessResponse | null,
): RetrievalLabCallout | null {
  if (!retrievalLab || !response) return null;
  if (response.query !== retrievalLab.query) return null;
  if (!runMatchesMissionGates(retrievalLab, response)) return null;
  const outcome = retrievalLabOutcome(retrievalLab, response, readiness);
  const targetPresent = retrievalLab.target_product_ids.every((productId) =>
    response.results.some((product) => product.product_id === productId));
  // Re-point the mission at another product and the name stops being printed
  // rather than being printed wrongly.
  const namesTheTarget =
    retrievalLab.target_product_ids.length === 1
    && retrievalLab.target_product_ids[0] === RETRIEVAL_LAB_TARGET.product_id;
  return {
    mission: retrievalLab,
    outcome,
    targetPresent,
    repaired: targetPresent && outcome.tone === "fixed",
    blocked: outcome.tone === "unhealthy",
    missingHeading: namesTheTarget
      ? `Issue reproduced: the ${RETRIEVAL_LAB_TARGET.name} is missing`
      : outcome.title,
  };
}

/**
 * Which of the three callouts is on screen, as a class.
 *
 * Amber for an environment fault and red for the seam, drawn apart on purpose
 * and the same way `.lab-outcome` draws them: "the room is wrong" and "the code
 * you were sent here to fix is wrong" ask for different work.
 */
function calloutTone(callout: RetrievalLabCallout): string {
  if (callout.blocked) return "unhealthy";
  return callout.repaired ? "fixed" : "broken";
}

/**
 * What a Shop search is doing while it runs, in the storefront's own words.
 *
 * This list read "Cohere Embed v4 / FTS / pg_trgm / HNSW / SQL eligibility / RRF
 * / Cohere Rerank" — seven implementation names on a shopping surface, for a
 * shopper who is waiting for products. The five customer-facing steps are the
 * same request; the model and index names are on the Playground, next to the
 * measurements that justify naming them.
 */
const retrievalScope = [
  "Understanding your words",
  "Exact terms",
  "Close spelling",
  "Meaning match",
  "Only what you can buy",
  "Combining the results",
  "Reranking the shortlist",
];

const shopSuggestedQueries = [
  catalogGhostQueries[0],
  catalogGhostQueries[1],
  catalogGhostQueries[3],
];

function HybridRetrievalTrace() {
  return (
    <section
      className="hybrid-retrieval-trace"
      aria-live="polite"
      aria-label="What this search is doing"
    >
      <header>
        <div>
          <p>Searching the catalog</p>
          <strong>Finding and ranking the best matches</strong>
        </div>
        <span className="hybrid-retrieval-status">
          <LoaderCircle className="spin" size={14} aria-hidden="true" />
          In progress
        </span>
      </header>
      <p className="hybrid-retrieval-scope">
        This is the same path every Mosaic search takes. The steps are not
        streamed one by one, so nothing here claims an order it cannot see.
      </p>
      <ul aria-label="Steps in this search">
        {retrievalScope.map((step) => <li key={step}>{step}</li>)}
      </ul>
    </section>
  );
}

export function CatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expandedFilters, setExpandedFilters] = useState<Record<FilterSection, boolean>>({
    categories: true,
    brand: false,
    price: false,
    availability: false,
    rating: false,
  });
  const [retrieval, setRetrieval] = useState<SearchResponse | null>(null);
  const [retrievalLoading, setRetrievalLoading] = useState(false);
  const [retrievalError, setRetrievalError] = useState("");
  const [retrievalQuery, setRetrievalQuery] = useState(searchParams.get("q") ?? "");
  /**
   * Bumped by the Lab 1 callout's "Search again".
   *
   * The repair happens in another window, so re-running has to re-ask Aurora for
   * the same request rather than re-render the response the browser is already
   * holding. Nothing else about the request changes, which is why a counter is
   * the whole mechanism.
   */
  const [retrievalNonce, setRetrievalNonce] = useState(0);
  /** The workshop Code Editor's origin, or null where the deployment has none. */
  const [codeEditorUrl, setCodeEditorUrl] = useState<string | null>(null);
  /**
   * What Aurora reports about itself, read once, so the Lab 1 callout can tell a
   * missing index from an unrepaired one. Null until it lands and after a failed
   * read, which `retrievalLabOutcome` treats as "nothing known" rather than as a
   * fault.
   */
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  /** The request `retrieval` answered, so a response held over from an earlier
   * one is never mistaken for the run this URL is asking for. */
  const [servedRequest, setServedRequest] = useState("");
  const [agentOpen, setAgentOpen] = useState(false);
  const [highlightedProductId, setHighlightedProductId] = useState<number | null>(null);
  const [drawerProductId, setDrawerProductId] = useState<number | null>(null);
  const [domainsAtEnd, setDomainsAtEnd] = useState(false);
  const domainTabsRef = useRef<HTMLElement>(null);
  const filterSheetRef = useRef<HTMLElement>(null);
  const filterPreviouslyFocused = useRef<HTMLElement | null>(null);
  const resultsAnchorRef = useRef<HTMLDivElement>(null);
  /**
   * Where a lab arrival scrolls to, when there is a lab verdict to read.
   *
   * `?view=results` scrolls the results header to the top of the window, which
   * put the Lab 1 callout one line above the fold: a participant arriving from
   * the hero chip landed on a page of plausible headphones with the sentence
   * explaining them just off screen. The callout is the reason for the arrival,
   * so it is the anchor whenever it is on the page.
   */
  const labCalloutRef = useRef<HTMLElement>(null);
  const catalogRequestVersion = useRef(0);
  const retrievalRequestVersion = useRef(0);
  const handledAskDeepLink = useRef(false);
  const handledResultsView = useRef("");
  const restoreAgentFocusOnClose = useRef(false);
  const reduceMotion = useReducedMotion() ?? false;

  const domain = (searchParams.get("domain") || undefined) as Domain | undefined;
  const offset = Number(searchParams.get("offset") ?? 0);
  const sort = searchParams.get("sort") ?? "featured";
  const availability = (searchParams.get("availability") || undefined) as
    | Availability
    | undefined;
  const minRating = searchParams.get("min_rating");
  const categoryKey = searchParams.get("category_key") || undefined;
  const brand = searchParams.get("brand") || undefined;
  const minPriceCents = searchParams.get("min_price_cents");
  const maxPriceCents = searchParams.get("max_price_cents");
  const inStockOnly = searchParams.get("in_stock_only") === "true";
  const lowPrice = priceFromCents(minPriceCents, 0);
  const highPrice = priceFromCents(maxPriceCents, priceCeiling);
  const activeQuery = searchParams.get("q")?.trim() ?? "";
  const requestedView = searchParams.get("view");
  const filters: SearchFilters = {
    domain,
    category_key: categoryKey,
    brand,
    availability,
    in_stock_only: inStockOnly || undefined,
    min_rating: minRating ? Number(minRating) : undefined,
    min_price_cents: minPriceCents ? Number(minPriceCents) : undefined,
    max_price_cents: maxPriceCents ? Number(maxPriceCents) : undefined,
  };
  const retrievalRequest = retrievalRequestKey(activeQuery, filters);
  const {
    answeredTurn,
    clear: clearAgentThread,
    examples: agentExamples,
    pending: agentPending,
    run: askAgent,
    turns: agentTurns,
  } = useAskMosaicConversation(filters);
  const activeFilterCount = [
    domain,
    categoryKey,
    brand,
    availability,
    inStockOnly ? "in_stock_only" : undefined,
    minRating,
    minPriceCents,
    maxPriceCents,
  ].filter(Boolean).length;
  // The panel holds a conversation, so Shop follows the newest exchange that
  // produced an answer: an in-flight follow-up leaves the current shortlist,
  // banner, and numbering in place until its own answer arrives.
  const agent = answeredTurn?.response ?? null;
  const agentQuestion = answeredTurn?.question ?? "";
  const labMission = mosaicRetrievalExamples.find(
    (mission) => mission.id === searchParams.get("mission") && mission.stage === "reason",
  );
  const labOutcome = labMission && (agent || answeredTurn?.error)
    ? agentLabOutcome(labMission, agent, answeredTurn?.error ?? "")
    : null;
  const labCallout = retrievalLabCallout(retrieval, readiness);

  const load = useCallback(() => {
    const version = catalogRequestVersion.current + 1;
    catalogRequestVersion.current = version;
    setLoading(true);
    setError("");
    api
      .catalog(filters, offset, pageSize, sort)
      .then((nextPage) => {
        if (version === catalogRequestVersion.current) setPage(nextPage);
      })
      .catch((cause) => {
        if (version !== catalogRequestVersion.current) return;
        setPage(null);
        setError(
          cause instanceof Error ? cause.message : "Catalog browsing is unavailable",
        );
      })
      .finally(() => {
        if (version === catalogRequestVersion.current) setLoading(false);
      });
  }, [
    domain,
    categoryKey,
    brand,
    availability,
    inStockOnly,
    minRating,
    minPriceCents,
    maxPriceCents,
    offset,
    sort,
  ]);

  useEffect(() => {
    // Hybrid search owns the visible product grid. Loading merchandising rows
    // and four browse facets alongside it does not improve the result and made
    // each filter change wait on unrelated catalog work.
    if (activeQuery) {
      catalogRequestVersion.current += 1;
      setLoading(false);
      setError("");
      return;
    }
    load();
  }, [activeQuery, load]);

  useEffect(() => {
    const version = retrievalRequestVersion.current + 1;
    retrievalRequestVersion.current = version;
    setRetrievalQuery(activeQuery);
    setRetrievalError("");
    if (!activeQuery) {
      setRetrieval(null);
      setRetrievalLoading(false);
      return;
    }

    setRetrievalLoading(true);
    const request = retrievalRequest;
    api
      .search(activeQuery, filters, { limit: pageSize, rerank: true })
      .then((response) => {
        if (version !== retrievalRequestVersion.current) return;
        setRetrieval(response);
        setServedRequest(request);
      })
      .catch((cause) => {
        if (version !== retrievalRequestVersion.current) return;
        setRetrieval(null);
        setRetrievalError(
          cause instanceof Error ? cause.message : "Hybrid retrieval is unavailable",
        );
      })
      .finally(() => {
        if (version === retrievalRequestVersion.current) setRetrievalLoading(false);
      });
  }, [
    activeQuery,
    domain,
    categoryKey,
    brand,
    availability,
    inStockOnly,
    minRating,
    minPriceCents,
    maxPriceCents,
    retrievalNonce,
  ]);

  /**
   * The Code Editor origin, read once from `/api/health`.
   *
   * Health answers from process configuration and never touches Aurora, so the
   * Lab 1 callout can offer a way into the file even while the cluster is the
   * thing that is wrong.
   */
  useEffect(() => {
    let active = true;
    api.health().then(
      (health) => {
        if (active) setCodeEditorUrl(health.code_editor_url ?? null);
      },
      () => {
        if (active) setCodeEditorUrl(null);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  /**
   * Index and corpus health, read once beside it.
   *
   * Once, not per search: readiness answers about the cluster rather than about
   * a request, and re-asking on every keystroke would put a schema inspection
   * behind Shop's search box. A failed read leaves it null, which is the honest
   * "not checked" -- announcing an environment fault on the strength of a failed
   * status call is the same error as blaming the participant for a missing
   * index.
   */
  useEffect(() => {
    let active = true;
    api.readiness().then(
      (state) => {
        if (active) setReadiness(state);
      },
      () => {
        if (active) setReadiness(null);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  /**
   * The served run's own id, recorded on Shop's own URL.
   *
   * The header's Playground entry is built from this URL and nothing else, so a
   * run held only in component state would reach the in-page hand-off and not
   * the header one. Replaced rather than pushed: this records the request
   * already on screen, it is not somewhere a shopper navigated to.
   *
   * Only the run that answers the request the URL is currently making. A
   * response outlives its own request -- the grid keeps showing it while the
   * next search runs -- and recording it against the new query would hand the
   * Playground a run from a question nobody asked.
   */
  const servedSearchEventId = retrieval && servedRequest === retrievalRequest
    ? retrieval.search_event_id
    : "";

  useEffect(() => {
    const recorded = searchParams.get("event") ?? "";
    if (recorded === servedSearchEventId) return;
    const next = new URLSearchParams(searchParams);
    if (servedSearchEventId) next.set("event", servedSearchEventId);
    else next.delete("event");
    setSearchParams(next, { replace: true });
  }, [servedSearchEventId, searchParams, setSearchParams]);

  // Keyed on the view a hand-off asked for rather than on the whole query
  // string: any other parameter changing while the scroll is still queued would
  // re-run this effect, and its cleanup would cancel the frame it had already
  // scheduled. Recording the served run above does exactly that.
  useEffect(() => {
    if (
      requestedView !== "results"
      || !activeQuery
      || retrievalLoading
      || (!retrieval && !retrievalError)
    ) {
      return;
    }
    const requestKey = resultsViewKey(window.location.search);
    if (handledResultsView.current === requestKey) return;
    handledResultsView.current = requestKey;
    const frame = window.requestAnimationFrame(() => {
      (labCalloutRef.current ?? resultsAnchorRef.current)?.scrollIntoView?.({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    activeQuery,
    reduceMotion,
    requestedView,
    retrieval,
    retrievalError,
    retrievalLoading,
  ]);

  /**
   * The assist rail collapses the product grid from three columns to two, so
   * toggling it reflows the whole shop canvas in one frame. A view transition
   * cross-fades that reflow instead of letting it snap; where the API is
   * missing or the visitor prefers reduced motion, the plain state change
   * keeps the instant behavior. flushSync forces the commit inside the
   * snapshot callback so the transition captures the finished layout.
   */
  const setAssistOpen = useCallback((next: boolean) => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || typeof document.startViewTransition !== "function") {
      setAgentOpen(next);
      return;
    }
    document.startViewTransition(() => {
      flushSync(() => setAgentOpen(next));
    });
  }, []);

  useEffect(() => {
    if (
      handledAskDeepLink.current
      || (searchParams.get("ask") !== "1" && searchParams.get("mode") !== "agent")
    ) {
      return;
    }
    handledAskDeepLink.current = true;
    setAssistOpen(true);
  }, [activeQuery, searchParams, setAssistOpen]);

  useEffect(() => {
    if (!filtersOpen) return;
    filterPreviouslyFocused.current = (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    );
    const unlockScroll = lockBodyScroll();
    const layer = filterSheetRef.current?.parentElement;
    const background = [
      ...Array.from(layer?.parentElement?.children ?? []).filter(
        (element) => element !== layer,
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
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFiltersOpen(false);
    };
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        filterSheetRef.current?.querySelectorAll<HTMLElement>(
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
        filterSheetRef.current?.focus();
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
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("keydown", trapFocus);
    const frame = window.requestAnimationFrame(() => {
      filterSheetRef.current
        ?.querySelector<HTMLElement>('button[aria-label="Close filters"]')
        ?.focus();
    });
    return () => {
      unlockScroll();
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("keydown", trapFocus);
      for (const { element, inert, ariaHidden } of prior) {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
      const restoreTarget = filterPreviouslyFocused.current;
      if (restoreTarget?.isConnected) restoreTarget.focus();
    };
  }, [filtersOpen]);

  useLayoutEffect(() => {
    if (agentOpen || !restoreAgentFocusOnClose.current) return;
    restoreAgentFocusOnClose.current = false;
    document.querySelector<HTMLElement>(
      activeQuery ? ".shop-assist-rail" : ".shop-console-note-action",
    )?.focus();
  }, [activeQuery, agentOpen]);

  /**
   * Closing the panel also has to retire the deep links that open it.
   *
   * `?ask=1`, `?mode=agent`, and a lab `?mission=` all open Ask Mosaic on
   * arrival, so leaving them on the URL means a reload, a back navigation, or a
   * copied link reopens the panel the participant just dismissed.
   */
  const closeAgent = useCallback(() => {
    restoreAgentFocusOnClose.current = true;
    setAssistOpen(false);
    setHighlightedProductId(null);
    const next = new URLSearchParams(searchParams);
    const openers = ["ask", "mode", "mission"].filter((name) => next.has(name));
    if (!openers.length) return;
    for (const name of openers) next.delete(name);
    setSearchParams(next);
  }, [searchParams, setAssistOpen, setSearchParams]);

  function update(name: string, value?: string, resetPage = true) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value);
    else next.delete(name);
    if (resetPage) next.delete("offset");
    setSearchParams(next);
  }

  function searchCatalog(query: string) {
    const trimmed = query.trim();
    if (trimmed.length < 2) return;
    const next = new URLSearchParams(searchParams);
    next.set("q", trimmed);
    next.delete("offset");
    next.delete("ask");
    next.delete("mode");
    // The run recorded here answered the previous query. Dropping it with the
    // query it belongs to leaves no render in which the hand-off links carry a
    // run from one search and the words of another.
    next.delete("event");
    next.set("view", "results");
    setSearchParams(next);
  }

  function clearSearch() {
    const next = new URLSearchParams(searchParams);
    next.delete("q");
    next.delete("ask");
    next.delete("mode");
    next.delete("view");
    next.delete("event");
    setRetrieval(null);
    setRetrievalError("");
    setRetrievalQuery("");
    setSearchParams(next);
  }

  /** Built from nothing rather than filtered down, so `event` goes with the
   * gates: the run on screen was retrieved under them, and it is not the run
   * this URL will be asking for once they are gone. */
  function clearFilters() {
    const next = new URLSearchParams();
    if (sort !== "featured") next.set("sort", sort);
    if (activeQuery) next.set("q", activeQuery);
    setSearchParams(next);
  }

  function commitPrice(low: number, high: number) {
    const nextLow = Math.round(Math.min(low, high) * 100);
    const nextHigh = Math.round(Math.max(low, high) * 100);
    const next = new URLSearchParams(searchParams);
    if (nextLow > 0) next.set("min_price_cents", String(nextLow));
    else next.delete("min_price_cents");
    if (nextHigh < priceCeilingCents) next.set("max_price_cents", String(nextHigh));
    else next.delete("max_price_cents");
    next.delete("offset");
    setSearchParams(next);
  }

  /**
   * One entry point: the panel is the composer. There used to be a second
   * composer in the Shop header, so asking meant typing into one field, then
   * watching a different field slide in beside the answer.
   */
  function openAgent() {
    restoreAgentFocusOnClose.current = true;
    setAssistOpen(true);
  }

  function clearAgentResults() {
    clearAgentThread();
    setAssistOpen(false);
    setHighlightedProductId(null);
  }

  /**
   * Same discard, without dismissing the panel.
   *
   * "Clear shortlist" on the Shop rail closes the panel because it is a Shop
   * control acting on Shop; the panel's own control has to leave the reader
   * inside the conversation it just emptied, back on the entry state. The version
   * bump is what orphans a stream that is still open: the turn id it would patch
   * is gone, and the guard in `askAgent` stops it reviving a cleared thread.
   */
  function clearAgentConversation() {
    clearAgentThread();
    setHighlightedProductId(null);
  }

  function toggleFilter(section: FilterSection) {
    setExpandedFilters((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  function openFilterSection(section?: FilterSection) {
    const expanded = section ?? "categories";
    setExpandedFilters({
      categories: expanded === "categories",
      brand: expanded === "brand",
      price: expanded === "price",
      availability: expanded === "availability",
      rating: expanded === "rating",
    });
    setFiltersOpen(true);
  }

  // Going deeper on an Ask Mosaic pick opens the product beside the
  // conversation instead of scrolling the page away from it.
  function openProductDrawer(productId: number) {
    setHighlightedProductId(productId);
    setDrawerProductId(productId);
  }

  function closeProductDrawer() {
    setDrawerProductId(null);
  }

  const catalogCategories = page?.facets.category_key ?? [];
  const catalogBrands = page?.facets.brand ?? [];
  const baseProducts = retrieval?.results ?? page?.products ?? [];
  const agentProducts = agent?.recommendations.length
    ? agent.recommendations
    : null;
  const visibleProducts = mergeVisibleProducts(agentProducts, baseProducts);
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const gridImages = productImageMap(visibleProducts);
  const assistRanks = new Map(
    (agentProducts ?? []).map((product, index) => [product.product_id, index + 1]),
  );

  const revealMoreDomains = () => {
    const tabs = domainTabsRef.current;
    if (!tabs) return;
    const nextAtEnd = !domainsAtEnd;
    tabs.scrollTo({
      left: nextAtEnd ? tabs.scrollWidth : 0,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
    setDomainsAtEnd(nextAtEnd);
  };
  const syncDomainScroll = () => {
    const tabs = domainTabsRef.current;
    if (!tabs) return;
    setDomainsAtEnd(
      tabs.scrollLeft >= Math.max(0, tabs.scrollWidth - tabs.clientWidth - 1),
    );
  };
  const filterChips: Array<{
    key: string;
    label: string;
    remove: () => void;
  }> = [];

  if (domain) {
    filterChips.push({
      key: "domain",
      label: domainLabels[domain],
      remove: () => update("domain"),
    });
  }
  if (categoryKey) {
    filterChips.push({
      key: "category",
      label: formatCategoryKey(categoryKey),
      remove: () => update("category_key"),
    });
  }
  if (brand) {
    filterChips.push({
      key: "brand",
      label: brand,
      remove: () => update("brand"),
    });
  }
  if (availability) {
    filterChips.push({
      key: "availability",
      label: formatAvailability(availability),
      remove: () => update("availability"),
    });
  }
  if (inStockOnly && !availability) {
    filterChips.push({
      key: "in-stock-only",
      label: "In stock",
      remove: () => update("in_stock_only"),
    });
  }
  if (minRating) {
    filterChips.push({
      key: "rating",
      label: `${minRating}+ stars`,
      remove: () => update("min_rating"),
    });
  }
  if (minPriceCents || maxPriceCents) {
    filterChips.push({
      key: "price",
      label: `$${lowPrice.toLocaleString()}-${
        highPrice >= priceCeiling ? `${priceCeiling.toLocaleString()}+` : highPrice.toLocaleString()
      }`,
      remove: () => {
        const next = new URLSearchParams(searchParams);
        next.delete("min_price_cents");
        next.delete("max_price_cents");
        next.delete("offset");
        setSearchParams(next);
      },
    });
  }

  return (
    <div className={agentOpen ? "page mosaic-catalog-page assist-open" : "page mosaic-catalog-page"}>
      <div className={agentOpen ? "shop-canvas assist-open" : "shop-canvas"}>
        <section className="shop-main">
          <div className={activeQuery ? "shop-hero is-searching" : "shop-hero"}>
            {/* With a query on the URL the page's job is the result list, so
                the still steps aside. Not rendered rather than hidden: a hidden
                <img> still downloads, and this page arrives from Discover
                already searching. */}
            {activeQuery ? null : (
              <div className="shop-hero-photo">
                <img
                  src="/assets/images/mosaic/hero-editorial-still.webp"
                  alt=""
                  width={1672}
                  height={941}
                  fetchPriority="high"
                  decoding="async"
                />
              </div>
            )}

            {/* No "SHOP" label above the headline: the header's active nav entry
                already says where the participant is. */}
            <header className="shop-heading">
              <h1 className="commerce-display">
                Find what fits <em>your world.</em>
              </h1>
              <p className="shop-lede">
                Search in your own words, browse with intention, or ask Mosaic
                for help deciding.
              </p>
            </header>

            <div className="shop-console">
              <div className="shop-console-search">
                <section className="shop-search" aria-label="Mosaic product search">
                  <CatalogSearchComposer
                    initialValue={retrievalQuery}
                    pending={retrievalLoading}
                    leadingIcon={<GenerativeSearchIcon size={18} />}
                    placeholder="Search a product, model, or describe what you need"
                    submitIcon={<Send size={16} aria-hidden="true" />}
                    submitIconOnly
                    onSubmit={searchCatalog}
                  />
                </section>

                <div className="shop-suggested" aria-label="Suggested searches">
                  <span>Suggested for you</span>
                  {shopSuggestedQueries.map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      onClick={() => searchCatalog(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>

              {/* The pitch for Ask Mosaic, and only while it is closed. With the
                  panel open this sat beside a panel headed "Ask Mosaic" making the
                  same three promises, so the fold carried the invitation twice. */}
              {agentOpen ? null : (
              <aside className="shop-console-note" aria-label="What Ask Mosaic does">
                <small>Ask Mosaic</small>
                <strong>I can help you choose.</strong>
                <ul>
                  <li>
                    <Check size={13} aria-hidden="true" />
                    Turns your request into catalog constraints
                  </li>
                  <li>
                    <Check size={13} aria-hidden="true" />
                    Compares candidates on record data
                  </li>
                  <li>
                    <Check size={13} aria-hidden="true" />
                    Cites the evidence behind each pick
                  </li>
                </ul>
                <p className="shop-console-note-mobile">
                  Turns your request into constraints, compares candidates, and
                  cites every pick.
                </p>
                <button
                  className="mosaic-ask-button shop-console-note-action"
                  type="button"
                  aria-label="Ask Mosaic"
                  aria-expanded={agentOpen}
                  onClick={openAgent}
                >
                  <Sparkles size={15} aria-hidden="true" />
                  {agent ? "Return to Ask Mosaic" : "Ask Mosaic"}
                </button>
                <img
                  className="shop-console-note-photo"
                  src="/assets/images/mosaic/echobud-s2.webp"
                  alt=""
                  width={1200}
                  height={1200}
                  loading="lazy"
                  decoding="async"
                />
              </aside>
              )}
            </div>
          </div>

          <div className="shop-controls">
            <div className="shop-domain-scroller">
              <nav
                className="shop-domain-tabs"
                aria-label="Product domains"
                ref={domainTabsRef}
                onScroll={syncDomainScroll}
              >
                {domainOptions.map((option) => (
                  <button
                    type="button"
                    className={domain === option.value ? "active" : ""}
                    aria-pressed={domain === option.value}
                    key={option.value ?? "all"}
                    onClick={() => update("domain", option.value)}
                  >
                    {option.label}
                    {domain === option.value ? (
                      <motion.span
                        className="shop-domain-indicator"
                        layoutId="shop-domain-indicator"
                        transition={
                          reduceMotion
                            ? { duration: 0 }
                            : { duration: 0.24, ease: EASE_OUT }
                        }
                      />
                    ) : null}
                  </button>
                ))}
              </nav>
              <button
                className="shop-domain-next"
                type="button"
                aria-label={domainsAtEnd ? "Show earlier product domains" : "Show more product domains"}
                onClick={revealMoreDomains}
              >
                {domainsAtEnd
                  ? <ChevronLeft size={18} aria-hidden="true" />
                  : <ChevronRight size={18} aria-hidden="true" />}
              </button>
            </div>
          </div>

          <div className="shop-filter-toolbar" aria-label="Product filters">
            <button
              className="shop-filter-button all"
              type="button"
              aria-expanded={filtersOpen}
              aria-controls="shop-filter-sheet"
              onClick={() => openFilterSection()}
            >
              <SlidersHorizontal size={16} />
              All filters
              {activeFilterCount ? <span>{activeFilterCount}</span> : null}
            </button>
            <button type="button" onClick={() => openFilterSection("categories")}>
              {categoryKey ? formatCategoryKey(categoryKey) : "Category"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => openFilterSection("brand")}>
              {brand || "Brand"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => openFilterSection("price")}>
              {minPriceCents || maxPriceCents ? `$${lowPrice}-$${highPrice}` : "Price"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => openFilterSection("rating")}>
              {minRating ? `${minRating}+ stars` : "Rating"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button
              className={inStockOnly ? "shop-stock-toggle active" : "shop-stock-toggle"}
              type="button"
              role="switch"
              aria-checked={inStockOnly}
              onClick={() => update("in_stock_only", inStockOnly ? undefined : "true")}
            >
              In stock
              <span aria-hidden="true"><i /></span>
            </button>
            {!retrieval ? (
              <label className="shop-sort">
                <span className="sr-only">Sort catalog</span>
                <select value={sort} onChange={(event) => update("sort", event.target.value)}>
                  <option value="featured">Featured</option>
                  <option value="rating">Highest rated</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                  <option value="newest">Newest</option>
                </select>
                <ChevronDown size={15} aria-hidden="true" />
              </label>
            ) : null}
          </div>

          <AnimatePresence initial={false}>
            {filterChips.length ? (
              <motion.div
                className="shop-filter-chips"
                aria-label="Active filters"
                initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
                exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                transition={{ duration: reduceMotion ? 0.12 : 0.18, ease: EASE_OUT }}
                layout={!reduceMotion}
              >
                <AnimatePresence initial={false}>
                  {filterChips.map((chip) => (
                    <motion.button
                      type="button"
                      key={chip.key}
                      onClick={chip.remove}
                      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.94 }}
                      animate={reduceMotion ? { opacity: 1 } : { opacity: 1, scale: 1 }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.94 }}
                      transition={{ duration: reduceMotion ? 0.1 : 0.16, ease: EASE_OUT }}
                      layout={!reduceMotion}
                    >
                      {chip.label} <X size={13} />
                    </motion.button>
                  ))}
                </AnimatePresence>
                <button className="clear" type="button" onClick={clearFilters}>Clear all</button>
              </motion.div>
            ) : null}
          </AnimatePresence>

          {labOutcome ? <LabOutcomeBanner outcome={labOutcome} /> : null}

          {/* A callout, not a modal. The results it is about stay on screen
              underneath it: the point is that a page of plausible headphones and
              a missing product are the same screen. */}
          {labCallout ? (
            <section
              ref={labCalloutRef}
              className={`shop-lab-callout ${calloutTone(labCallout)}`}
              aria-label={`Lab ${retrievalLabNumber} outcome`}
            >
              {labCallout.blocked ? (
                <>
                  {/* No file, no task, and no claim about the participant's
                      work. Readiness says an index this scenario needs is not
                      there, and the same empty trigram channel that an
                      unrepaired CTE produces is what they would be sent to fix.
                      "Search again" stays: re-applying the schema happens in
                      another window, exactly as a repair does. */}
                  <h2>{labCallout.outcome.title}</h2>
                  <p>{labCallout.outcome.detail}</p>
                  <div className="shop-lab-callout-actions">
                    <CodeEditorLink href={codeEditorUrl} />
                    <button
                      type="button"
                      onClick={() => setRetrievalNonce((run) => run + 1)}
                    >
                      Search again
                    </button>
                  </div>
                </>
              ) : labCallout.repaired ? (
                <>
                  <h2>Repair verified</h2>
                  <p>{labCallout.outcome.detail}</p>
                  {/* Promoted out of the collapsed disclosure below, and rendered
                      only here, so the participant is offered one way through to
                      the evidence rather than the same link twice. */}
                  <Link
                    className="shop-lab-callout-playground"
                    href={playgroundQueryHref(
                      retrieval!.query,
                      retrieval!.applied_filters,
                      retrieval!.search_event_id,
                    )}
                  >
                    See how this was retrieved in the {RETRIEVAL_SURFACE.label}
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </Link>
                </>
              ) : (
                <>
                  <h2>
                    {labCallout.targetPresent
                      ? labCallout.outcome.title
                      : labCallout.missingHeading}
                  </h2>
                  <p>
                    This is Lab {retrievalLabNumber}'s deliberate fault, not a gap
                    in the catalog. {labCallout.outcome.detail}
                  </p>
                  <p className="shop-lab-callout-edit">
                    Edit <code>{labCallout.mission.participant_edit!.file}</code>:
                    {" "}
                    {labCallout.mission.participant_edit!.task}
                  </p>
                  <div className="shop-lab-callout-actions">
                    <CodeEditorLink href={codeEditorUrl} />
                    <button
                      type="button"
                      onClick={() => setRetrievalNonce((run) => run + 1)}
                    >
                      Search again
                    </button>
                  </div>
                </>
              )}
            </section>
          ) : null}

          {agentProducts || activeQuery || retrievalError ? (
            <div
              ref={resultsAnchorRef}
              className={retrievalError ? "shop-query-state error" : "shop-query-state"}
            >
              <span>
                <strong>
                  {agentProducts
                    ? "Ask Mosaic shortlist"
                    : retrievalError
                      ? "Search unavailable"
                      : "Results for"}
                </strong>
                {agentProducts ? agentQuestion : retrievalError || activeQuery}
              </span>
              {agentProducts ? (
                <button type="button" onClick={clearAgentResults}>Clear shortlist</button>
              ) : activeQuery ? (
                <button type="button" onClick={clearSearch}>Clear search</button>
              ) : null}
            </div>
          ) : null}

          <div className="shop-results-heading">
            <p>
              {agentProducts ? (
                <>
                  <strong>{agentProducts.length}</strong> linked recommendations
                  <small> · numbered in Shop and Ask Mosaic</small>
                </>
              ) : retrieval ? (
                <>
                  <strong>{retrieval.results.length}</strong> best matches
                  <small> · chosen from {retrieval.diagnostics?.candidate_counts.fused_pool ?? "-"} candidates</small>
                </>
              ) : page ? (
                <>
                  {page.total ? (
                    <>
                      <strong>
                        {Math.min(offset + 1, page.total)}-
                        {Math.min(offset + pageSize, page.total)}
                      </strong>
                      {" "}of {page.total.toLocaleString()} products
                    </>
                  ) : (
                    <><strong>0</strong> products</>
                  )}
                </>
              ) : retrievalLoading && activeQuery ? "Searching products" : "Loading catalog"}
            </p>
            {agent && !agentOpen ? (
              <button type="button" onClick={openAgent}>
                <Sparkles size={15} /> Reopen Ask Mosaic
              </button>
            ) : null}
          </div>

          {/* One disclosure, and the bridge out of it. Everything a shopper needs
              is above; a participant who wants the SQL follows their own words
              into the Playground rather than retyping them there. */}
          {retrieval ? (
            <details className="shop-ranking-receipt">
              <summary>
                <span>Why these results, in this order</span>
                <small>Where each match came from, and what reranking changed</small>
              </summary>
              <SearchRetrievalReceipt response={retrieval} />
              {/* Suppressed while the Lab 1 callout carries the same link above,
                  which is where a participant who has just repaired the arm is
                  looking. */}
              {labCallout?.repaired ? null : (
                <Link
                  className="shop-ranking-playground"
                  href={playgroundQueryHref(
                    retrieval.query,
                    retrieval.applied_filters,
                    retrieval.search_event_id,
                  )}
                >
                  See how this was retrieved in the {RETRIEVAL_SURFACE.label}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              )}
            </details>
          ) : null}

          {loading && !page && !activeQuery ? <CatalogLoadingState /> : null}
          {retrievalLoading ? <HybridRetrievalTrace /> : null}
          {retrievalLoading && !page && !retrieval ? <CatalogLoadingState /> : null}
          {error ? <ErrorState message={error} onRetry={load} /> : null}
          {!error && (page || retrieval || agentProducts) ? (
            <div
              className={retrievalLoading ? "shop-products loading" : "shop-products"}
              aria-busy={retrievalLoading}
            >
              {visibleProducts.length ? (
                <motion.div
                  className="product-grid shop-product-grid"
                  key={`${retrieval?.search_event_id ?? agent?.agent_run_id ?? page?.offset ?? 0}-${sort}-${categoryKey ?? "all"}-${domain ?? "all"}`}
                  initial={
                    reduceMotion
                      ? { opacity: 0.82 }
                      : { opacity: 0.62, filter: "blur(2px)" }
                  }
                  animate={
                    reduceMotion
                      ? { opacity: 1 }
                      : { opacity: 1, filter: "blur(0px)" }
                  }
                  transition={{ duration: reduceMotion ? 0.12 : 0.24, ease: EASE_OUT }}
                >
                  {visibleProducts.map((product) => (
                    <ProductCard
                      key={product.product_id}
                      product={product}
                      imageSrc={gridImages.get(product.product_id)}
                      variant="catalog"
                      showSignals={Boolean(retrieval || agentProducts)}
                      assistRank={assistRanks.get(product.product_id)}
                      highlighted={highlightedProductId === product.product_id}
                      onAssistFocus={setHighlightedProductId}
                    />
                  ))}
                </motion.div>
              ) : (
                <section className="shop-empty">
                  <Search size={24} />
                  <h2>No eligible products</h2>
                  <p>Remove a filter or clear the search to see more products.</p>
                </section>
              )}
              {!retrieval && !agentProducts && page ? (
                <div className="shop-pagination">
                  <button
                    type="button"
                    disabled={offset === 0}
                    onClick={() => update("offset", String(Math.max(0, offset - pageSize)), false)}
                  >
                    <ChevronLeft size={17} /> Previous
                  </button>
                  <span>
                    Page {offset / pageSize + 1} of{" "}
                    {Math.max(1, Math.ceil(page.total / pageSize)).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    disabled={offset + pageSize >= page.total}
                    onClick={() => update("offset", String(offset + pageSize), false)}
                  >
                    Next <ChevronRight size={17} />
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <AskMosaic
          imageByProductId={gridImages}
          open={agentOpen}
          seedQuery={activeQuery}
          contextFilters={filterChips.map((chip) => chip.label)}
          turns={agentTurns}
          pending={agentPending}
          examples={agentExamples}
          highlightedProductId={highlightedProductId}
          onClose={closeAgent}
          onClear={clearAgentConversation}
          onRun={(query) => void askAgent(query)}
          onHighlight={setHighlightedProductId}
          onSelectProduct={openProductDrawer}
        />

        <ProductDrawer
          productId={drawerProductId}
          imageByProductId={gridImages}
          onClose={closeProductDrawer}
        />

        {/* The rail is pinned to the same right edge the filter sheet and the
            assist panel arrive on. It glides off rather than unmounting flat:
            popping out in a single frame read as the incoming sheet shaking.
            Motion owns the y axis too, or its transform would drop the CSS
            translateY(-50%) centering and the rail would jump half its height. */}
        <AnimatePresence initial={false}>
          {activeQuery && !agentOpen && !filtersOpen ? (
            <motion.button
              className="shop-assist-rail"
              type="button"
              aria-label="Try Ask Mosaic with these results"
              onClick={openAgent}
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 56, y: "-50%" }}
              animate={reduceMotion ? { opacity: 1 } : { opacity: 1, x: 0, y: "-50%" }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 56, y: "-50%" }}
              transition={{ duration: reduceMotion ? 0.1 : 0.2, ease: EASE_OUT }}
            >
              <Sparkles size={15} aria-hidden="true" />
              <span>Try Ask Mosaic</span>
              <ChevronLeft size={15} aria-hidden="true" />
            </motion.button>
          ) : null}
        </AnimatePresence>
      </div>

      <AnimatePresence initial={false}>
        {filtersOpen ? (
          <div className="shop-filter-layer">
            <motion.button
              className="shop-filter-backdrop"
              type="button"
              aria-label="Close filters"
              onClick={() => setFiltersOpen(false)}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduceMotion ? 0.1 : 0.18 }}
            />
            <motion.aside
              ref={filterSheetRef}
              className="shop-filter-sheet"
              id="shop-filter-sheet"
              role="dialog"
              aria-modal="true"
              aria-labelledby="shop-filter-title"
              tabIndex={-1}
              initial={reduceMotion ? { opacity: 0 } : { x: "100%" }}
              animate={reduceMotion ? { opacity: 1 } : { x: 0 }}
              exit={reduceMotion ? { opacity: 0 } : { x: "100%" }}
              transition={{ duration: reduceMotion ? 0.12 : 0.28, ease: EASE_OUT }}
            >
            <header>
              <div>
                <h2 id="shop-filter-title">Filters</h2>
                <p>Results update immediately.</p>
              </div>
              <button type="button" aria-label="Close filters" onClick={() => setFiltersOpen(false)}>
                <X size={20} />
              </button>
            </header>

            <div className="shop-filter-body">
              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => toggleFilter("categories")}
                  aria-expanded={expandedFilters.categories}
                >
                  Category
                  {expandedFilters.categories ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {expandedFilters.categories ? (
                  <div className="shop-filter-options">
                    <label>
                      <input
                        type="radio"
                        name="category"
                        checked={!categoryKey}
                        onChange={() => update("category_key")}
                      />
                      <span>All products</span>
                      {page ? <small>{page.total.toLocaleString()}</small> : null}
                    </label>
                    {catalogCategories.slice(0, 8).map((item) => (
                      <label key={item.value}>
                        <input
                          type="radio"
                          name="category"
                          checked={categoryKey === item.value}
                          onChange={() => update("category_key", item.value)}
                        />
                        <span>{formatCategoryKey(item.value)}</span>
                        <small>{item.count.toLocaleString()}</small>
                      </label>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => toggleFilter("brand")}
                  aria-expanded={expandedFilters.brand}
                >
                  Brand
                  {expandedFilters.brand ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {expandedFilters.brand ? (
                  <div className="shop-filter-options">
                    <label>
                      <input
                        type="radio"
                        name="brand"
                        checked={!brand}
                        onChange={() => update("brand")}
                      />
                      <span>All brands</span>
                    </label>
                    {catalogBrands.slice(0, 10).map((item) => (
                      <label key={item.value}>
                        <input
                          type="radio"
                          name="brand"
                          checked={brand === item.value}
                          onChange={() => update("brand", item.value)}
                        />
                        <span>{item.value}</span>
                        <small>{item.count.toLocaleString()}</small>
                      </label>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => toggleFilter("price")}
                  aria-expanded={expandedFilters.price}
                >
                  Price range
                  {expandedFilters.price ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {expandedFilters.price ? (
                  <div className="shop-price-range">
                    <div>
                      <span>${lowPrice.toLocaleString()}</span>
                      <span>
                        ${highPrice.toLocaleString()}
                        {highPrice >= priceCeiling ? "+" : ""}
                      </span>
                    </div>
                    <div
                      className="shop-price-track"
                      style={{
                        ...({
                          "--low": `${(lowPrice / priceCeiling) * 100}%`,
                          "--high": `${(highPrice / priceCeiling) * 100}%`,
                        } as CSSProperties),
                      }}
                    >
                      <input
                        type="range"
                        aria-label="Minimum price"
                        min={0}
                        max={priceCeiling}
                        step={priceStep}
                        value={lowPrice}
                        onChange={(event) => commitPrice(Number(event.target.value), highPrice)}
                      />
                      <input
                        type="range"
                        aria-label="Maximum price"
                        min={0}
                        max={priceCeiling}
                        step={priceStep}
                        value={highPrice}
                        onChange={(event) => commitPrice(lowPrice, Number(event.target.value))}
                      />
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => toggleFilter("availability")}
                  aria-expanded={expandedFilters.availability}
                >
                  Availability
                  {expandedFilters.availability ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {expandedFilters.availability ? (
                  <div className="shop-filter-options">
                    {availabilityOptions.map((option) => (
                      <label key={option.value || "all"}>
                        <input
                          type="radio"
                          name="availability"
                          checked={(availability ?? "") === option.value}
                          onChange={() => update("availability", option.value || undefined)}
                        />
                        <span>{option.label}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => toggleFilter("rating")}
                  aria-expanded={expandedFilters.rating}
                >
                  Customer rating
                  {expandedFilters.rating ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {expandedFilters.rating ? (
                  <div className="shop-rating-options">
                    {ratingThresholds.map((threshold) => (
                      <label key={threshold}>
                        <input
                          type="radio"
                          name="min-rating"
                          checked={Number(minRating) === threshold}
                          onChange={() => update("min_rating", String(threshold))}
                        />
                        <span aria-hidden="true">
                          {Array.from({ length: threshold }).map((_, index) => (
                            <Star key={index} size={13} fill="currentColor" />
                          ))}
                        </span>
                        <small>&amp; up</small>
                      </label>
                    ))}
                    <label>
                      <input
                        type="radio"
                        name="min-rating"
                        checked={!minRating}
                        onChange={() => update("min_rating")}
                      />
                      <span>Any rating</span>
                    </label>
                  </div>
                ) : null}
              </section>
            </div>

            <footer>
              <button type="button" onClick={clearFilters}>Clear all</button>
              <button className="primary" type="button" onClick={() => setFiltersOpen(false)}>
                Done
              </button>
            </footer>
            </motion.aside>
          </div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
