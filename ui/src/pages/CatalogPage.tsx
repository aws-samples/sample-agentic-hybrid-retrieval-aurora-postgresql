import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LoaderCircle,
  Search,
  Sparkles,
  Star,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  CSSProperties,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "../api";
import { AskMosaic } from "../components/AskMosaic";
import type { AskMosaicTurn } from "../components/AskMosaic";
import { ProductCard } from "../components/ProductCard";
import { productImageMap } from "../media";
import { SearchComposer } from "../components/SearchComposer";
import { ErrorState, LoadingState } from "../components/States";
import {
  formatAvailability,
  formatCategoryKey,
} from "../format";
import { useSearchParams } from "../navigation";
import type {
  Availability,
  CatalogPage,
  Domain,
  ProductSummary,
  RetrievalExample,
  SearchFilters,
  SearchResponse,
} from "../types";

const pageSize = 12;
const priceCeiling = 2000;
const priceStep = 25;
const priceCeilingCents = priceCeiling * 100;
const ratingThresholds = [5, 4, 3, 2, 1] as const;

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

type FilterSection = "categories" | "price" | "availability" | "rating";

function priceFromCents(value: string | null, fallback: number) {
  if (value === null) return fallback;
  const cents = Number(value);
  if (!Number.isFinite(cents)) return fallback;
  return Math.min(Math.max(cents / 100, 0), priceCeiling);
}

/**
 * One starter question per domain, from the validated eval set.
 *
 * `/api/retrieval/examples` serves `data/evals/demo_queries.jsonl` deduplicated
 * in file order, so taking the first query of each domain is deterministic:
 * every participant sees the same three, they cover all three domains, and they
 * are questions the eval suite actually scores rather than copy written for the
 * panel.
 */
function starterQuestions(examples: RetrievalExample[]): string[] {
  const firstByDomain = new Map<Domain, string>();
  for (const example of examples) {
    if (!firstByDomain.has(example.domain)) {
      firstByDomain.set(example.domain, example.query);
    }
  }
  return [...firstByDomain.values()];
}

/** The most recent exchange that produced an answer, or null before any does. */
function lastAnswered(turns: AskMosaicTurn[]): AskMosaicTurn | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    if (turns[index].response) return turns[index];
  }
  return null;
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

const retrievalTraceSteps = [
  {
    label: "Request dispatched",
    detail: "Hard filters apply inside every retrieval arm",
  },
  {
    label: "Embed and retrieve",
    detail: "Cohere Embed v4 · FTS · pg_trgm · HNSW",
  },
  {
    label: "Fuse and rerank",
    detail: "RRF · Cohere Rerank",
  },
  {
    label: "Return ranked products",
    detail: "Eligibility and provenance",
  },
];

function HybridRetrievalTrace() {
  return (
    <section
      className="hybrid-retrieval-trace"
      role="status"
      aria-label="Hybrid retrieval trace"
    >
      <header>
        <div>
          <p>Retrieval trace</p>
          <strong>Building a ranked candidate set</strong>
        </div>
        <span className="hybrid-retrieval-status">
          <LoaderCircle className="spin" size={14} aria-hidden="true" />
          In progress
        </span>
      </header>
      <ol>
        {retrievalTraceSteps.map((step, index) => (
          <li key={step.label} className={index === 0 ? "complete" : ""}>
            <span className="hybrid-retrieval-marker" aria-hidden="true">
              {index === 0 ? <Check size={13} /> : index + 1}
            </span>
            <span>
              <strong>{step.label}</strong>
              <small>{step.detail}</small>
            </span>
          </li>
        ))}
      </ol>
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
    price: true,
    availability: true,
    rating: true,
  });
  const [retrieval, setRetrieval] = useState<SearchResponse | null>(null);
  const [retrievalLoading, setRetrievalLoading] = useState(false);
  const [retrievalError, setRetrievalError] = useState("");
  const [retrievalQuery, setRetrievalQuery] = useState(searchParams.get("q") ?? "");
  const [agentTurns, setAgentTurns] = useState<AskMosaicTurn[]>([]);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentStarters, setAgentStarters] = useState<string[]>([]);
  const [highlightedProductId, setHighlightedProductId] = useState<number | null>(null);
  const retrievalRequestVersion = useRef(0);
  const agentRequestVersion = useRef(0);
  const handledAskDeepLink = useRef(false);

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
  const agentPending = agentTurns.some((turn) => turn.loading);
  const answeredTurn = lastAnswered(agentTurns);
  const agent = answeredTurn?.response ?? null;
  const agentQuestion = answeredTurn?.question ?? "";

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .catalog(filters, offset, pageSize, sort)
      .then(setPage)
      .catch((cause) => {
        setPage(null);
        setError(
          cause instanceof Error ? cause.message : "Catalog browsing is unavailable",
        );
      })
      .finally(() => setLoading(false));
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
    api
      .search(activeQuery, filters, { limit: pageSize, rerank: true })
      .then((response) => {
        if (version === retrievalRequestVersion.current) setRetrieval(response);
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
  ]);

  /**
   * The starters are an affordance, not content, so a failed fetch is not an
   * error state: the entry state simply offers no examples and the participant
   * types their own. The panel's error surface belongs to the ask itself, which
   * is the request whose failure a participant has to be told about.
   */
  useEffect(() => {
    let active = true;
    api
      .examples()
      .then((examples) => {
        if (active) setAgentStarters(starterQuestions(examples));
      })
      .catch(() => {
        if (active) setAgentStarters([]);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (
      handledAskDeepLink.current
      || (searchParams.get("ask") !== "1" && searchParams.get("mode") !== "agent")
    ) {
      return;
    }
    handledAskDeepLink.current = true;
    setAgentOpen(true);
  }, [activeQuery, searchParams]);

  useEffect(() => {
    if (!filtersOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFiltersOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [filtersOpen]);

  /**
   * Closing the panel also has to retire the deep links that open it.
   *
   * `?ask=1`, `?mode=agent`, and a lab `?mission=` all open Ask Mosaic on
   * arrival, so leaving them on the URL means a reload, a back navigation, or a
   * copied link reopens the panel the participant just dismissed.
   */
  const closeAgent = useCallback(() => {
    setAgentOpen(false);
    setHighlightedProductId(null);
    const next = new URLSearchParams(searchParams);
    const openers = ["ask", "mode", "mission"].filter((name) => next.has(name));
    if (!openers.length) return;
    for (const name of openers) next.delete(name);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

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
    setSearchParams(next);
  }

  function clearSearch() {
    const next = new URLSearchParams(searchParams);
    next.delete("q");
    next.delete("ask");
    next.delete("mode");
    setRetrieval(null);
    setRetrievalError("");
    setRetrievalQuery("");
    setSearchParams(next);
  }

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
    setAgentOpen(true);
  }

  function clearAgentResults() {
    agentRequestVersion.current += 1;
    setAgentTurns([]);
    setAgentOpen(false);
    setHighlightedProductId(null);
  }

  /**
   * Append one exchange and stream into it.
   *
   * The version ref still gates every write, because clearing the conversation
   * has to orphan a stream that is already open: the id it would patch is gone,
   * and the guard stops it from reviving the panel.
   */
  async function askAgent(question: string) {
    const trimmed = question.trim();
    if (trimmed.length < 2 || agentPending) return;
    const version = agentRequestVersion.current + 1;
    agentRequestVersion.current = version;
    setAgentOpen(true);
    setAgentTurns((turns) => [
      ...turns,
      {
        id: version,
        question: trimmed,
        response: null,
        streamed: "",
        stage: "understand",
        stageDetail:
          "Working out what you need and which catalog constraints that implies.",
        error: "",
        loading: true,
      },
    ]);
    const patch = (change: Partial<AskMosaicTurn>) => {
      setAgentTurns((turns) => turns.map(
        (turn) => (turn.id === version ? { ...turn, ...change } : turn),
      ));
    };
    try {
      await api.agentStream(trimmed, filters, (event) => {
        if (version !== agentRequestVersion.current) return;
        if (event.type === "stage") {
          patch({ stage: event.id, stageDetail: event.detail });
        } else if (event.type === "answer_start") {
          patch({
            response: event.response,
            stage: "answer",
            stageDetail:
              "Writing the recommendation from the products it found and the specs and reviews behind them.",
          });
        } else if (event.type === "answer_delta") {
          const { delta } = event;
          setAgentTurns((turns) => turns.map(
            (turn) => (turn.id === version
              ? { ...turn, streamed: turn.streamed + delta }
              : turn),
          ));
        } else {
          patch({
            response: event.response,
            streamed: event.response.answer,
            stage: null,
            stageDetail: "",
          });
        }
      });
    } catch (cause) {
      if (version !== agentRequestVersion.current) return;
      patch({
        stage: null,
        stageDetail: "",
        error: cause instanceof Error ? cause.message : "Ask Mosaic is unavailable",
      });
    } finally {
      if (version === agentRequestVersion.current) patch({ loading: false });
    }
  }

  function toggleFilter(section: FilterSection) {
    setExpandedFilters((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  function focusCatalogProduct(productId: number) {
    setHighlightedProductId(productId);
    window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(`[data-product-id="${productId}"]`)
        ?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
          block: "center",
        });
    });
  }

  const catalogCategories = page?.facets.category_key ?? [];
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
          <header className="shop-heading">
            <p className="shop-kicker">Shop</p>
            <h1>The Mosaic edit</h1>
            <p className="shop-lede">
              Browse the 120-product Mosaic edit, photographed in one light.
              Search and Ask Mosaic retrieve across the complete
              500,000-product catalog.
            </p>
          </header>

          <section className="shop-search" aria-label="Mosaic product search">
            <SearchComposer
              compact
              initialValue={retrievalQuery}
              pending={retrievalLoading}
              submitLabel="Search"
              placeholder="Search a product, model, or describe what you need"
              onSubmit={searchCatalog}
            />
            <button
              className="shop-search-ask"
              type="button"
              aria-label="Ask Mosaic"
              aria-expanded={agentOpen}
              onClick={openAgent}
            >
              <Sparkles size={15} aria-hidden="true" />
              {agent ? "Return to Ask Mosaic" : "Ask Mosaic"}
            </button>
          </section>

          <div className="shop-controls">
            <nav className="shop-domain-tabs" aria-label="Product domains">
              {domainOptions.map((option) => (
                <button
                  type="button"
                  className={domain === option.value ? "active" : ""}
                  key={option.value ?? "all"}
                  onClick={() => update("domain", option.value)}
                >
                  {option.label}
                </button>
              ))}
            </nav>
            <div className="shop-control-actions">
              <button
                className="shop-filter-button"
                type="button"
                aria-expanded={filtersOpen}
                aria-controls="shop-filter-sheet"
                onClick={() => setFiltersOpen(true)}
              >
                <SlidersHorizontal size={17} />
                Filters
                {activeFilterCount ? <span>{activeFilterCount}</span> : null}
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
          </div>

          {filterChips.length ? (
            <div className="shop-filter-chips" aria-label="Active filters">
              {filterChips.map((chip) => (
                <button type="button" key={chip.key} onClick={chip.remove}>
                  {chip.label} <X size={13} />
                </button>
              ))}
              <button className="clear" type="button" onClick={clearFilters}>Clear all</button>
            </div>
          ) : null}

          {agentProducts || activeQuery || retrievalError ? (
            <div className={retrievalError ? "shop-query-state error" : "shop-query-state"}>
              <span>
                <strong>
                  {agentProducts
                    ? "Ask Mosaic shortlist"
                    : retrievalError
                      ? "Search unavailable"
                      : "Hybrid results"}
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
                  <strong>{retrieval.results.length}</strong> ranked products
                  <small> · {retrieval.diagnostics?.candidate_counts.fused_pool ?? "-"} fused candidates</small>
                </>
              ) : page ? (
                <>
                  <strong>{offset + 1}-{Math.min(offset + pageSize, page.total)}</strong>
                  {" "}of {page.total.toLocaleString()} products
                </>
              ) : "Loading catalog"}
            </p>
            {agent && !agentOpen ? (
              <button type="button" onClick={() => setAgentOpen(true)}>
                <Sparkles size={15} /> Reopen Ask Mosaic
              </button>
            ) : null}
          </div>

          {loading && !page && !activeQuery ? <LoadingState label="Loading products" /> : null}
          {retrievalLoading ? <HybridRetrievalTrace /> : null}
          {error ? <ErrorState message={error} onRetry={load} /> : null}
          {!error && (page || retrieval || agentProducts) ? (
            <div
              className={retrievalLoading ? "shop-products loading" : "shop-products"}
              aria-busy={retrievalLoading}
            >
              {visibleProducts.length ? (
                <div
                  className="product-grid shop-product-grid"
                  key={`${retrieval?.search_event_id ?? agent?.agent_run_id ?? page?.offset ?? 0}-${sort}-${categoryKey ?? "all"}-${domain ?? "all"}`}
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
                </div>
              ) : (
                <section className="shop-empty">
                  <Search size={24} />
                  <h2>No eligible products</h2>
                  <p>Remove a constraint or clear the current search to widen the candidate set.</p>
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
          shopQuery={activeQuery}
          seedQuery={activeQuery}
          filterCount={activeFilterCount}
          turns={agentTurns}
          pending={agentPending}
          starters={agentStarters}
          highlightedProductId={highlightedProductId}
          onClose={closeAgent}
          onRun={(query) => void askAgent(query)}
          onHighlight={setHighlightedProductId}
          onSelectProduct={focusCatalogProduct}
        />
      </div>

      {filtersOpen ? (
        <div className="shop-filter-layer">
          <button
            className="shop-filter-backdrop"
            type="button"
            aria-label="Close filters"
            onClick={() => setFiltersOpen(false)}
          />
          <aside
            className="shop-filter-sheet"
            id="shop-filter-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="shop-filter-title"
          >
            <header>
              <div>
                <p className="eyebrow">Narrow the candidate set</p>
                <h2 id="shop-filter-title">Filters</h2>
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
                Show products
              </button>
            </footer>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
