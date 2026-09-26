import { sourceFilters, useCatalogSource } from "../catalogSource";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Search,
  Sparkles,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "motion/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { Link } from "wouter";
import { api } from "../api";
import { catalogData, type BrowseRequest } from "../catalogData";
import { AskMosaic } from "../components/AskMosaic";
import { useAskMosaicMemory } from "../components/AskMosaicMemory";
import { ShopSearchDetails } from "../components/ShopSearchDetails";
import { RetrievalJourney } from "../components/RetrievalJourney";
import { ContinueWorkspace } from "../components/ContinueWorkspace";
import { ScopedComparison } from "../components/ScopedComparison";
import { ShopFilterSheet, type FilterSection } from "../components/ShopFilterSheet";
import {
  CatalogSearchComposer,
} from "../components/CatalogSearchComposer";
import { CodeEditorLink } from "../components/CodeEditorLink";
import { CoverageNotice } from "../components/CoverageNotice";
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
  shopSearchExamples,
  mosaicRetrievalExamples,
  mosaicLabManifest,
  type MosaicLabMission,
} from "../labMissions";
import {
  RETRIEVAL_SURFACE,
  forwardedSearchFilters,
  playgroundProofHref,
  playgroundQueryHref,
  useSearchParams,
} from "../navigation";
import { lockBodyScroll } from "../scrollLock";
import "../shop-editorial.css";
import type {
  Availability,
  CatalogPage,
  Domain,
  ProductSummary,
  ReadinessResponse,
  SearchFilters,
  SearchResponse,
} from "../types";

const priceCeiling = 2000;
const priceStep = 25;
const priceCeilingCents = priceCeiling * 100;
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

const domainOptions: Array<{ value?: Domain; label: string }> = [
  { label: "All products" },
  { value: "home_office", label: "Workspace" },
  { value: "consumer_electronics", label: "Electronics" },
  { value: "running_fitness", label: "Running & fitness" },
];

const domainLabels: Record<Domain, string> = {
  consumer_electronics: "Electronics",
  running_fitness: "Running & fitness",
  home_office: "Workspace",
};

function priceFromCents(value: string | null, fallback: number) {
  if (value === null) return fallback;
  const cents = Number(value);
  if (!Number.isFinite(cents)) return fallback;
  return Math.min(Math.max(cents / 100, 0), priceCeiling);
}

function mergeVisibleProducts(
  recommendations: ProductSummary[] | null,
  products: ProductSummary[],
  limit: number,
) {
  if (!recommendations?.length) return products;
  const recommendationIds = new Set(
    recommendations.map((product) => product.product_id),
  );
  return [
    ...recommendations,
    ...products.filter((product) => !recommendationIds.has(product.product_id)),
  ].slice(0, limit);
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
 * guide's exercise link. Both the words and the gates have to match: the same words under
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
  return {
    mission: retrievalLab,
    outcome,
    targetPresent,
    repaired: targetPresent && outcome.tone === "fixed",
    blocked: outcome.tone === "unhealthy",
    missingHeading: retrievalLab.target_display_name
      ? `Issue reproduced: the ${retrievalLab.target_display_name} is missing`
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
  "Applying your filters",
  "Combining the results",
  "Reranking the shortlist",
];

const shopSuggestedQueries = mosaicLabManifest.playground.requests;

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
  const { real, dataset_id: dataset, loaded: sourceLoaded } = useCatalogSource();
  const [searchParams, setSearchParams] = useSearchParams();
  const [catalogPage, setPage] = useState<CatalogPage | null>(null);
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
  const [retrievalResponse, setRetrieval] = useState<SearchResponse | null>(null);
  const [showSearchDetails, setShowSearchDetails] = useState(false);
  /**
   * Products the participant ticked to compare, in the order they ticked them.
   *
   * Keyed to nothing but this page: a comparison is authorised by one
   * retrieval's grant, so the selection is dropped whenever the served run
   * changes below. Carrying it across runs would let a tick made under one
   * search be sent against another search's scope, which the server would
   * refuse -- correctly, and confusingly.
   */
  const [comparisonIds, setComparisonIds] = useState<number[]>([]);
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
  /**
   * The price handles while a drag or key press is still moving them, ahead of
   * the URL. A native range input fires on every pixel of a drag; committing
   * each one to the URL search-params history spammed a filter-driven search
   * request per pixel. Null once the URL has caught up to the last draft, so
   * the drag position and the committed one can never show two different
   * numbers.
   */
  const [priceDraft, setPriceDraft] = useState<{ low: number; high: number } | null>(null);
  const priceCommitTimer = useRef<number | undefined>(undefined);
  const domainTabsRef = useRef<HTMLElement>(null);
  const filterSheetRef = useRef<HTMLElement>(null);
  const filterPreviouslyFocused = useRef<HTMLElement | null>(null);
  const resultsAnchorRef = useRef<HTMLDivElement>(null);
  /**
   * Where a lab arrival scrolls to, when there is a lab verdict to read.
   *
   * `?view=results` scrolls the results header to the top of the window, which
   * put the Lab 1 callout one line above the fold: a participant arriving from
   * the guide's exercise link landed on a page of plausible headphones with the sentence
   * explaining them just off screen. The callout is the reason for the arrival,
   * so it is the anchor whenever it is on the page.
   */
  const labCalloutRef = useRef<HTMLElement>(null);
  const catalogRequestVersion = useRef(0);
  const retrievalRequestVersion = useRef(0);
  const retrievalController = useRef<AbortController | null>(null);
  const handledAskDeepLink = useRef(false);
  const handledResultsView = useRef("");
  const restoreAgentFocusOnClose = useRef(false);
  const reduceMotion = useReducedMotion() ?? false;

  const { domain, category_key: categoryKey } = sourceFilters({
    domain: (searchParams.get("domain") || undefined) as Domain | undefined,
    category_key: searchParams.get("category_key") || undefined,
  }, real);
  const offset = Number(searchParams.get("offset") ?? 0);
  const sort = searchParams.get("sort") ?? "featured";
  const availability = (searchParams.get("availability") || undefined) as
    | Availability
    | undefined;
  const minRating = searchParams.get("min_rating");
  const brand = searchParams.get("brand") || undefined;
  const minPriceCents = searchParams.get("min_price_cents");
  const maxPriceCents = searchParams.get("max_price_cents");
  const inStockOnly = searchParams.get("in_stock_only") === "true";
  const attributeParams = searchParams.get("attributes");
  const committedLowPrice = priceFromCents(minPriceCents, 0);
  const committedHighPrice = priceFromCents(maxPriceCents, priceCeiling);
  // The draft wins while the URL has not caught up to it yet, so the track and
  // labels always agree with the handle the reader is holding.
  const lowPrice = priceDraft?.low ?? committedLowPrice;
  const highPrice = priceDraft?.high ?? committedHighPrice;
  const activeQuery = searchParams.get("q")?.trim() ?? "";
  const browseCollection = searchParams.get("collection") === "all" || domain || categoryKey
    ? "all" : "workspace";
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
    attributes: forwardedSearchFilters(searchParams).attributes as SearchFilters["attributes"],
  };
  const retrievalRequest = retrievalRequestKey(activeQuery, filters);
  // Products and their receipts must answer the same request as the heading,
  // including while a replacement search is pending or has failed.
  const retrieval = activeQuery && servedRequest === retrievalRequest ? retrievalResponse : null;
  const page = activeQuery ? null : catalogPage;
  const labMission = mosaicRetrievalExamples.find(
    (mission) => mission.id === searchParams.get("mission") && mission.stage === "reason",
  );
  const memory = useAskMosaicMemory(agentOpen && !labMission);
  const {
    answeredTurn,
    clear: clearAgentThread,
    stop: stopAgentThread,
    suggestions: agentSuggestions,
    pending: agentPending,
    run: askAgent,
    turns: agentTurns,
  } = useAskMosaicConversation(filters, !labMission && memory.enabled);
  const activeFilterCount = [
    domain,
    categoryKey,
    brand,
    availability,
    inStockOnly ? "in_stock_only" : undefined,
    minRating,
    minPriceCents,
    maxPriceCents,
    ...Object.keys(filters.attributes ?? {}),
  ].filter(Boolean).length;
  // The panel holds a conversation, so Shop follows the newest exchange that
  // produced an answer: an in-flight follow-up leaves the current shortlist,
  // banner, and numbering in place until its own answer arrives.
  const agent = answeredTurn?.contextKey === retrievalRequest ? answeredTurn.response : null;
  const agentQuestion = answeredTurn?.question ?? "";
  const labOutcome = labMission && (agent || answeredTurn?.error)
    ? agentLabOutcome(labMission, agent, answeredTurn?.error ?? "")
    : null;
  const labCallout = retrievalLabCallout(retrieval, readiness);
  const requestMission = coreMosaicLabs.find(
    (mission) => mission.id === searchParams.get("mission") && mission.query === activeQuery,
  );
  const rankMission = coreMosaicLabs.find(
    (mission) => mission.stage === "rank" && retrieval?.query === mission.query
      && runMatchesMissionGates(mission, retrieval),
  );
  const rankOutcome = rankMission && retrieval
    ? retrievalLabOutcome(rankMission, retrieval, readiness)
    : null;

  const load = useCallback(() => {
    const version = catalogRequestVersion.current + 1;
    catalogRequestVersion.current = version;
    const request: BrowseRequest = { dataset, filters, offset, sort, collection: browseCollection };
    const cached = catalogData.peek(request);
    setPage(cached ?? null);
    setLoading(!cached);
    setError("");
    catalogData
      .load(request)
      .then((nextPage) => {
        if (version !== catalogRequestVersion.current) return;
        setPage(nextPage);
        const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
        if (!connection?.saveData && nextPage.offset + nextPage.limit < nextPage.total) {
          void catalogData.load({ ...request, offset: nextPage.offset + nextPage.limit }).catch(() => {});
        }
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
    browseCollection,
    dataset,
    attributeParams,
  ]);

  // Drop the draft only once the URL agrees with it, never on a timer of its
  // own: clearing it first would show the pre-drag price for one render while
  // `setSearchParams` is still catching up.
  useEffect(() => {
    if (
      priceDraft
      && priceDraft.low === committedLowPrice
      && priceDraft.high === committedHighPrice
    ) {
      setPriceDraft(null);
    }
  }, [priceDraft, committedLowPrice, committedHighPrice]);

  useEffect(() => () => window.clearTimeout(priceCommitTimer.current), []);

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
    if (sourceLoaded !== false) load();
  }, [activeQuery, load, sourceLoaded]);

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
    const controller = new AbortController();
    retrievalController.current = controller;
    api
      .search(activeQuery, filters, {
        limit: requestMission?.top_k,
        rerank: true,
        signal: controller.signal,
      })
      .then((response) => {
        if (version !== retrievalRequestVersion.current) return;
        setRetrieval(response);
        setServedRequest(request);
      })
      .catch((cause) => {
        if (controller.signal.aborted || version !== retrievalRequestVersion.current) return;
        setRetrieval(null);
        setRetrievalError(
          cause instanceof Error ? cause.message : "Hybrid retrieval is unavailable",
        );
      })
      .finally(() => {
        if (version !== retrievalRequestVersion.current) return;
        setRetrievalLoading(false);
        if (retrievalController.current === controller) retrievalController.current = null;
      });
    // React runs this before the next call to the effect body, so a filter or
    // query change abandons the request that answers the stale one before
    // Aurora finishes it, rather than only ignoring its response.
    return () => controller.abort();
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
    attributeParams,
    requestMission?.id,
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
   * Only the run that answers the current request can authorize this hand-off.
   * The previous response may still be held in state while its replacement loads.
   */
  const servedSearchEventId = retrieval?.search_event_id ?? "";

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
    const transition = document.startViewTransition(() => {
      flushSync(() => setAgentOpen(next));
    });
    // A hidden document or an interrupting transition rejects both promises
    // with InvalidStateError after the state change has already applied, so
    // the only work left is keeping that rejection out of the console.
    transition.ready.catch(() => undefined);
    transition.finished.catch(() => undefined);
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

  // The overlay removes inert during effect cleanup, before focus can return.
  useEffect(() => {
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
    if (name === "domain") next.set("collection", "all");
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
    // Repeating a request must retry even when no URL filter has changed.
    if (trimmed === activeQuery) setRetrievalNonce((run) => run + 1);
  }

  // A complete suggested need replaces incompatible browse filters and stale receipts.
  function searchSuggestion(suggestion: { query: string; filters: SearchFilters }) {
    const next = new URLSearchParams();
    if (sort !== "featured") next.set("sort", sort);
    next.set("q", suggestion.query);
    next.set("view", "results");
    for (const [key, value] of Object.entries(sourceFilters(suggestion.filters, real))) {
      if (value !== undefined) next.set(key, typeof value === "object" ? JSON.stringify(value) : String(value));
    }
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
    window.clearTimeout(priceCommitTimer.current);
    setPriceDraft(null);
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
   * Hold the handle position locally and commit it after a short pause in
   * dragging, rather than on every `input` event a native range fires. Each
   * commit replaces browser history and starts a new catalog search, so
   * committing every pixel of a drag was one history entry and one search
   * request per pixel.
   */
  function draftPrice(low: number, high: number) {
    setPriceDraft({ low, high });
    window.clearTimeout(priceCommitTimer.current);
    priceCommitTimer.current = window.setTimeout(() => commitPrice(low, high), 300);
  }

  /** Commit immediately, so releasing the handle does not wait out the debounce. */
  function flushPendingPrice() {
    if (priceCommitTimer.current === undefined) return;
    window.clearTimeout(priceCommitTimer.current);
    priceCommitTimer.current = undefined;
    if (priceDraft) commitPrice(priceDraft.low, priceDraft.high);
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

  const catalogCategories = catalogPage?.facets.category_key ?? [];
  const catalogBrands = catalogPage?.facets.brand ?? [];
  const baseProducts = retrieval?.results ?? page?.products ?? [];
  const agentProducts = agent?.recommendations.length
    ? agent.recommendations
    : null;
  const pageSize = catalogPage?.limit ?? Math.max(1, baseProducts.length);
  const visibleProducts = mergeVisibleProducts(agentProducts, baseProducts, pageSize);
  // Use the same product photos in Shop and Playground, including agent picks.
  const gridImages = productImageMap(visibleProducts);
  const assistRanks = new Map(
    (agentProducts ?? []).map((product, index) => [product.product_id, index + 1]),
  );

  /**
   * The retrieval whose grant a comparison would be sent against, or null.
   *
   * Browsing the catalog is not a retrieval: there is no search event, so
   * nothing has granted anything, and there is no scope to authorise a
   * comparison. That is why the tick boxes appear with a served run and not
   * before it -- the affordance and the authority arrive together.
   */
  const comparisonScopeId = retrieval?.search_event_id ?? null;

  /**
   * Drop the selection when the served run changes.
   *
   * A tick is a claim about one retrieval's results. Carried into the next run
   * it would be sent against a scope that never granted that product, and the
   * server would refuse it -- correctly, but the participant would read the
   * refusal as the comparison being broken rather than as their selection being
   * stale.
   */
  useEffect(() => {
    setComparisonIds([]);
  }, [comparisonScopeId]);

  function updateComparison(productId: number, checked: boolean) {
    setComparisonIds((current) => {
      if (!checked) return current.filter((id) => id !== productId);
      // The server takes two to five; offering a sixth tick that can only be
      // refused is worse than not offering it.
      if (current.includes(productId) || current.length >= 5) return current;
      return [...current, productId];
    });
  }

  function comparisonProps(productId: number) {
    if (!comparisonScopeId) return {};
    return {
      showCompare: true,
      compareChecked: comparisonIds.includes(productId),
      compareDisabled: comparisonIds.length >= 5 && !comparisonIds.includes(productId),
      onCompareChange: updateComparison,
    };
  }

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
  for (const [key, value] of Object.entries(filters.attributes ?? {})) {
    filterChips.push({
      key: `attribute-${key}`,
      label: `${formatCategoryKey(key.replaceAll("_", "-"))}: ${
        typeof value === "boolean" ? (value ? "Yes" : "No") : JSON.stringify(value)
      }`,
      remove: () => {
        const next = new URLSearchParams(searchParams);
        const attributes = { ...filters.attributes };
        delete attributes[key];
        if (Object.keys(attributes).length) next.set("attributes", JSON.stringify(attributes));
        else next.delete("attributes");
        next.delete("offset");
        setSearchParams(next);
      },
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
            {/* No "SHOP" label above the headline: the header's active nav entry
                already says where the participant is. */}
            <header className="shop-heading">
              <h1 className="commerce-display">
                Find what fits <em>your world.</em>
              </h1>
              <p className="shop-lede">
                Search for a product, compare the details, or ask Mosaic to help you choose.
              </p>
            </header>

            {!activeQuery && !agentOpen ? <RetrievalJourney /> : null}

            <div className="shop-console">
              <div className="shop-console-search">
                <section className="shop-search" aria-label="Mosaic product search">
                  <CatalogSearchComposer
                    initialValue={retrievalQuery}
                    pending={retrievalLoading}
                    placeholder="Search a product, model or idea"
                    onSubmit={searchCatalog}
                  />
                </section>
                {readiness?.database.product_count ? (
                  <p className="shop-search-scope">
                    {retrievalLoading ? "Searching" : "Search"} {readiness.database.product_count.toLocaleString()} products
                  </p>
                ) : null}

                {real ? (
                  <div className="shop-search-examples" aria-label="Suggested searches">
                    <span>Explore</span>
                    {(["Keywords", "Typo", "Intent"] as const).map((kind) => (
                      <div className="shop-example-group" role="group" aria-label={`${kind} search examples`} key={kind}>
                        <span>{kind}</span>
                        {shopSearchExamples.filter((example) => example.kind === kind).map((example) => (
                          <button type="button" key={example.id} title={example.query} onClick={() => searchSuggestion(example)}>{example.label}</button>
                        ))}
                      </div>
                    ))}
                    <small>Different ways to ask. Every example uses the same search pipeline.</small>
                  </div>
                ) : (
                  <div className="shop-suggested" aria-label="Suggested searches">
                    <span>Explore</span>
                    {shopSuggestedQueries.map((suggestion) => (
                      <button type="button" key={suggestion.id} onClick={() => searchSuggestion(suggestion)}>{suggestion.shop_label}</button>
                    ))}
                  </div>
                )}
              </div>

              {/* The open assistant already carries this action's context. */}
              {agentOpen ? null : (
              <aside className="shop-console-note" aria-label="What Ask Mosaic does">
                <div className="shop-console-note-intro">
                  <h2>{agent ? "Keep comparing your options." : "A little help choosing?"}</h2>
                  <p>Tell Mosaic what matters. Get a considered shortlist, with the details behind each pick.</p>
                </div>
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
                {!activeQuery ? (
                  <button
                    type="button"
                    className={browseCollection === "workspace" ? "active" : ""}
                    aria-pressed={browseCollection === "workspace"}
                    onClick={() => {
                      const next = new URLSearchParams(searchParams);
                      for (const key of ["collection", "domain", "category_key", "offset"]) next.delete(key);
                      setSearchParams(next);
                    }}
                  >Workspace edit</button>
                ) : null}
                {domainOptions.filter(option => !real || option.value !== "running_fitness").filter(option => activeQuery || browseCollection === "all" || option.value !== "running_fitness").map((option) => (
                  <button
                    type="button"
                    className={domain === option.value && (activeQuery || browseCollection === "all") ? "active" : ""}
                    aria-pressed={domain === option.value && Boolean(activeQuery || browseCollection === "all")}
                    key={option.value ?? "all"}
                    onClick={() => update("domain", option.value)}
                  >
                    {option.label}
                    {domain === option.value && (activeQuery || browseCollection === "all") ? (
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

          {real ? <p className="shop-source-caption">Original product listings · Amazon Reviews 2023 · Open a listing for current prices and availability.</p> : null}
          <div className="shop-filter-toolbar" aria-label="Product filters">
            <button
              className="shop-filter-button all"
              type="button"
              aria-expanded={filtersOpen}
              aria-controls={filtersOpen ? "shop-filter-sheet" : undefined}
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
            <button type="button" hidden={real} onClick={() => openFilterSection("price")}>
              {minPriceCents || maxPriceCents ? `$${lowPrice}-$${highPrice}` : "Price"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => openFilterSection("rating")}>
              {minRating ? `${minRating}+ stars` : "Rating"}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            <button
              hidden={real}
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
                  {!real ? <option value="price_asc">Price: low to high</option> : null}
                  {!real ? <option value="price_desc">Price: high to low</option> : null}
                  {!real ? <option value="newest">Newest</option> : null}
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

          {/* The way back to the only surface that can grade this.
              Lab 3's card sends the participant here because the agent lives in
              Shop, and until this link existed nothing carried the finished run
              back: Prove could only read an `agentRunId` its own Reason stage
              had filled, so an exercise completed here had to be run a second
              time, and paid for a second time, to be graded.
              Offered whenever a run exists, including a declined one. Whether
              the run proves the lab is `POST /api/labs/3/proof`'s judgement,
              and deciding it here would be a second authority that could
              disagree with the first. */}
          {labMission && agent?.agent_run_id ? (
            <Link
              className="shop-lab-callout-playground"
              href={playgroundProofHref(labMission.id, agent.agent_run_id)}
            >
              Prove this run in the {RETRIEVAL_SURFACE.label}
              <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          ) : null}

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
                    href={`${playgroundQueryHref(
                      retrieval!.query,
                      retrieval!.applied_filters,
                      retrieval!.search_event_id,
                    )}&example=${encodeURIComponent(labCallout.mission.id)}#labs-stage-retrieve`}
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
                    <Link
                      className="shop-lab-callout-playground"
                      href={`${playgroundQueryHref(
                        retrieval!.query, retrieval!.applied_filters, retrieval!.search_event_id,
                      )}&example=${encodeURIComponent(labCallout.mission.id)}#labs-stage-retrieve`}
                    >
                      Inspect this run in the {RETRIEVAL_SURFACE.label}
                      <ArrowUpRight size={14} aria-hidden="true" />
                    </Link>
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

          {rankOutcome && rankMission && retrieval ? (
            <section ref={labCalloutRef} className={`shop-lab-callout ${rankOutcome.tone}`}
              aria-label={`Lab ${coreMosaicLabs.indexOf(rankMission) + 1} outcome`}>
              <h2>{rankOutcome.title}</h2>
              <p>{rankOutcome.detail}</p>
              <p>Compare the saved combined order with the final order. Then repeat the same request before and after the lab repair.</p>
              <table className="shop-lab-ranks">
                <caption>Where the first two results came from</caption>
                <thead><tr><th scope="col">Product</th><th scope="col">Before reranking</th><th scope="col">After reranking</th></tr></thead>
                <tbody>
                  {retrieval.results.slice(0, 2).map((product) => (
                      <tr key={product.product_id}>
                        <th scope="row">{product.brand} {product.model || product.title}</th>
                        <td>{product.signals?.pre_rerank_rank ?? "Unavailable"}</td>
                        <td>{product.signals?.final_rank ?? "Unavailable"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <div className="shop-lab-callout-actions">
                <Link className="shop-lab-callout-playground" href={`${playgroundQueryHref(
                  retrieval.query, retrieval.applied_filters, retrieval.search_event_id,
                )}&example=${encodeURIComponent(rankMission.id)}#labs-stage-rank`}>
                  Inspect this run in the {RETRIEVAL_SURFACE.label}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
                <button type="button" onClick={() => setRetrievalNonce((run) => run + 1)}>Search again</button>
              </div>
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
              {retrievalError ? <button type="button" onClick={() => setRetrievalNonce(value => value + 1)}>Retry search</button> : null}
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
                  <strong>{retrieval.results.length}</strong> {retrieval.results.length === 1 ? "best match" : "best matches"}
                  <small> · chosen from {retrieval.diagnostics?.candidate_counts.fused_pool ?? "-"} products found by search</small>
                  {/* The comparison itself stays below the results; this is the
                      acknowledgement a tick needs before the reader scrolls. */}
                  {comparisonScopeId && comparisonIds.length ? (
                    <small className="shop-compare-status" role="status">
                      {" · "}{comparisonIds.length} selected{comparisonIds.length > 1 ? ", compare below" : ", tick one more to compare"}
                    </small>
                  ) : null}
                </>
              ) : page ? (
                <>
                  {page.total ? (
                    <>
                      <strong>
                        {Math.min(page.offset + 1, page.total)}-
                        {Math.min(page.offset + pageSize, page.total)}
                      </strong>
                      {" "}of {page.total.toLocaleString()} {browseCollection === "workspace" ? "workspace picks" : "products"}
                    </>
                  ) : (
                    <><strong>0</strong> products</>
                  )}
                </>
              ) : retrievalError ? "No search results to show" : error ? "Catalog unavailable" : retrievalLoading && activeQuery ? "Searching products" : "Loading catalog"}
            </p>
              {!retrieval && !agentProducts && page ? (
                <nav className="shop-pagination" aria-label="Product pages">
                  <button
                    type="button"
                    disabled={loading || offset === 0}
                    onClick={() => update("offset", String(Math.max(0, offset - pageSize)), false)}
                  >
                    <ChevronLeft size={17} /> Previous
                  </button>
                  <span>
                    Page {page.offset / pageSize + 1} of{" "}
                    {Math.max(1, Math.ceil(page.total / pageSize)).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    disabled={loading || offset + pageSize >= page.total}
                    onClick={() => update("offset", String(offset + pageSize), false)}
                  >
                    Next <ChevronRight size={17} />
                  </button>
                </nav>
              ) : null}
            {answeredTurn?.response && !agentOpen ? (
              <button type="button" onClick={openAgent}>
                <Sparkles size={15} /> Reopen Ask Mosaic
              </button>
            ) : null}
          </div>

          {real && page && browseCollection === "workspace" && !activeQuery && !agentProducts ? (
            <p className="shop-collection-note">
              Headphones, chairs and monitors, chosen for clear specifications and useful comparisons.
              {sort === "featured" && !activeFilterCount ? " Featured picks alternate the three. Search covers the full catalog." : " Search covers the full catalog."}
            </p>
          ) : null}

          {/* Which words of the request the catalog does not carry. This used to
              render only on /search, a route nothing linked to, so coverage was
              measured and served and never shown to anybody. It belongs where
              the searching happens. */}
          <CoverageNotice coverage={retrieval?.coverage} />

          {/* One disclosure, and the bridge out of it. Everything a shopper needs
              is above; a participant who wants the SQL follows their own words
              into the Playground rather than retyping them there. */}
          {retrieval ? (
            <details className="shop-ranking-receipt">
              <summary>
                <span>{agentProducts ? "How the search results were ranked" : "Why these results, in this order"}</span>
                <small>{agentProducts ? "Ask Mosaic’s picks appear first in Shop. This record shows the original search order." : "Where each match came from, and what reranking changed"}</small>
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
          {retrieval && !agentProducts && !agentOpen && !retrievalLoading ? (
            <div className="shop-view-switch" role="group" aria-label="Results view">
              <button type="button" aria-pressed={!showSearchDetails} onClick={() => setShowSearchDetails(false)}>Shop</button>
              <button type="button" aria-pressed={showSearchDetails} onClick={() => setShowSearchDetails(true)}>Shop + search details</button>
            </div>
          ) : null}
          <div className={showSearchDetails && retrieval && !agentProducts && !agentOpen && !retrievalLoading ? "shop-results-layout with-inspector" : "shop-results-layout"}>
            {showSearchDetails && retrieval && !agentProducts && !agentOpen && !retrievalLoading ? (
              <ShopSearchDetails response={retrieval} onSelect={openProductDrawer} onHighlight={setHighlightedProductId} highlightedId={highlightedProductId} />
            ) : null}
          {!error && (page || retrieval || agentProducts) ? (
            <div
              className={retrievalLoading || loading ? "shop-products loading" : "shop-products"}
              aria-busy={retrievalLoading || loading}
            >
              {visibleProducts.length ? (
                <motion.div
                  className="product-grid shop-product-grid"
                  key={`${retrieval?.search_event_id ?? agent?.agent_run_id ?? page?.offset ?? 0}-${sort}-${categoryKey ?? "all"}-${domain ?? "all"}`}
                  initial={{ opacity: reduceMotion ? 1 : 0.82 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: reduceMotion ? 0 : 0.16, ease: EASE_OUT }}
                >
                  {visibleProducts.map((product) => (
                    <ProductCard
                      key={product.product_id}
                      product={product}
                      imageSrc={gridImages.get(product.product_id)}
                      variant="catalog"
                      showSignals={Boolean(retrieval || agentProducts)}
                      {...comparisonProps(product.product_id)}
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
              {/* Below the results rather than over them: the list stays where
                  the participant left it, which is what keeps the first result
                  in the first viewport on a 1366x768 laptop. */}
              {comparisonScopeId && comparisonIds.length > 1 ? (
                <ScopedComparison
                  searchEventId={comparisonScopeId}
                  productIds={comparisonIds}
                  onClear={() => setComparisonIds([])}
                />
              ) : null}

            </div>
          ) : null}
          </div>
          {!real && !activeQuery && !agentOpen && !agentProducts && !filterChips.length && browseCollection === "workspace" && offset === 0 && page && !error ? <ContinueWorkspace /> : null}
        </section>

        <AskMosaic
          memory={labMission ? undefined : memory}
          imageByProductId={gridImages}
          open={agentOpen}
          seedQuery={activeQuery}
          contextFilters={filterChips.map((chip) => chip.label)}
          turns={agentTurns}
          pending={agentPending}
          suggestions={agentSuggestions}
          highlightedProductId={highlightedProductId}
          onClose={closeAgent}
          onClear={clearAgentConversation}
          onStop={stopAgentThread}
          onRun={(query, suggestedFilters) => {
            if (!suggestedFilters) {
              void askAgent(query, filters, retrievalRequest);
              return;
            }
            const next = new URLSearchParams(searchParams);
            next.delete("event");
            next.delete("offset");
            const normalizedFilters = sourceFilters(suggestedFilters, real);
            for (const [key, value] of Object.entries(normalizedFilters)) {
              if (value !== undefined) next.set(key, typeof value === "object" ? JSON.stringify(value) : String(value));
            }
            setSearchParams(next);
            const requestFilters = { ...filters, ...normalizedFilters };
            void askAgent(query, requestFilters, retrievalRequestKey(activeQuery, requestFilters));
          }}
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

      <ShopFilterSheet
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        sheetRef={filterSheetRef}
        reduceMotion={reduceMotion}
        expandedFilters={expandedFilters}
        onToggleSection={toggleFilter}
        onUpdate={update}
        onClearAll={clearFilters}
        totalProductCount={page?.total}
        categoryKey={categoryKey}
        catalogCategories={catalogCategories}
        brand={brand}
        catalogBrands={catalogBrands}
        showPriceAndAvailability={!real}
        lowPrice={lowPrice}
        highPrice={highPrice}
        priceCeiling={priceCeiling}
        priceStep={priceStep}
        onPriceChange={draftPrice}
        onPriceCommit={flushPendingPrice}
        availability={availability}
        minRating={minRating}
      />
    </div>
  );
}
