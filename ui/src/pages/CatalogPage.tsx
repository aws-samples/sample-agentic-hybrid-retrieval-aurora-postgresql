import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Grid2X2,
  List,
  Sparkles,
  Star,
  SlidersHorizontal,
} from "lucide-react";
import { CSSProperties, useCallback, useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { MosaicMark } from "../components/MosaicMark";
import { ProductCard } from "../components/ProductCard";
import { SearchComposer } from "../components/SearchComposer";
import { ErrorState, LoadingState } from "../components/States";
import { formatAvailability, formatCategoryKey, formatPriceCompact, leafCategory } from "../format";
import { productImage } from "../media";
import { useSearchParams } from "../navigation";
import { showcaseCatalogPage } from "../showcase";
import type {
  AgentResponse,
  Availability,
  CatalogPage,
  Domain,
  ProductSummary,
  SearchFilters,
} from "../types";

// 3 columns x 4 rows. The premium cohort is 120 products, so this gives exactly
// 10 pages and matches the merchandising model in the schema package, which
// assigns every product a shop_page and shop_position on a 12-per-page grid.
const pageSize = 12;

type ShoppingPreference = {
  id: "focus" | "move" | "listen" | "travel";
  label: string;
  question: string;
  matches: (product: ProductSummary) => boolean;
};

const shoppingPreferences: ShoppingPreference[] = [
  {
    id: "focus",
    label: "Focus",
    question: "Recommend a calm, ergonomic setup for sustained focused work.",
    matches: (product) => product.domain === "home_office",
  },
  {
    id: "move",
    label: "Move",
    question: "Recommend dependable gear for daily movement and training.",
    matches: (product) => product.domain === "running_fitness",
  },
  {
    id: "listen",
    label: "Listen",
    question: "Recommend personal audio for focused listening and calls.",
    matches: (product) => product.category_path.startsWith("Audio"),
  },
  {
    id: "travel",
    label: "Travel",
    question: "Recommend compact, versatile essentials for working on the move.",
    matches: (product) =>
      product.category_key === "accessories" ||
      /(?:wireless earbuds|over-ear headphones)/i.test(product.category_path),
  },
];

function preferenceProducts(products: ProductSummary[], preference: ShoppingPreference) {
  const matching = products.filter(preference.matches);
  return (matching.length ? matching : products).slice(0, 3);
}

/**
 * Upper bound of the price slider. The reference board shows "$0 — $2000+" and
 * the live facets carry no price histogram, so the ceiling is a fixed rail with
 * the top handle meaning "no maximum" rather than a derived value that would
 * shift with every page of results.
 */
const priceCeiling = 2000;
const priceStep = 25;
const priceCeilingCents = priceCeiling * 100;

const ratingThresholds = [5, 4, 3, 2, 1] as const;

const availabilityOptions: Array<{ value: Availability | ""; label: string }> = [
  { value: "", label: "All availability" },
  { value: "in_stock", label: "In stock" },
  { value: "low_stock", label: "Low stock" },
  { value: "preorder", label: "Pre-order" },
];

type FilterSection = "categories" | "price" | "availability" | "rating";

function priceFromCents(value: string | null, fallback: number) {
  const cents = Number(value);
  if (!Number.isFinite(cents)) return fallback;
  return Math.min(Math.max(cents / 100, 0), priceCeiling);
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
  const [catalogView, setCatalogView] = useState<"grid" | "list">("grid");
  const [preference, setPreference] = useState<ShoppingPreference>(shoppingPreferences[0]);
  const [agent, setAgent] = useState<AgentResponse | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState("");
  const [agentQuestion, setAgentQuestion] = useState("");
  const domain = (searchParams.get("domain") || undefined) as Domain | undefined;
  const offset = Number(searchParams.get("offset") ?? 0);
  const sort = searchParams.get("sort") ?? "featured";
  const availability = (searchParams.get("availability") || undefined) as Availability | undefined;
  const minRating = searchParams.get("min_rating");
  const categoryKey = searchParams.get("category_key") || undefined;
  const brand = searchParams.get("brand") || undefined;
  const minPriceCents = searchParams.get("min_price_cents");
  const maxPriceCents = searchParams.get("max_price_cents");
  const lowPrice = priceFromCents(minPriceCents, 0);
  const highPrice = priceFromCents(maxPriceCents, priceCeiling);
  const filters: SearchFilters = {
    domain,
    category_key: categoryKey,
    brand,
    availability,
    min_rating: minRating ? Number(minRating) : undefined,
    min_price_cents: minPriceCents ? Number(minPriceCents) : undefined,
    max_price_cents: maxPriceCents ? Number(maxPriceCents) : undefined,
  };
  const activeFilterCount = [
    domain,
    categoryKey,
    brand,
    availability,
    minRating,
    minPriceCents,
    maxPriceCents,
  ].filter(Boolean).length;

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .catalog(filters, offset, pageSize, sort)
      .then(setPage)
      .catch(() => {
        setError("");
        setPage(showcaseCatalogPage(filters));
      })
      .finally(() => setLoading(false));
  }, [
    domain,
    categoryKey,
    brand,
    availability,
    minRating,
    minPriceCents,
    maxPriceCents,
    offset,
    sort,
  ]);

  useEffect(load, [load]);

  function update(name: string, value?: string, resetPage = true) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value);
    else next.delete(name);
    if (resetPage) next.delete("offset");
    setSearchParams(next);
  }

  function clearFilters() {
    const next = new URLSearchParams();
    if (sort !== "featured") next.set("sort", sort);
    setSearchParams(next);
  }

  /**
   * Writes both slider handles in one URL update. Calling `update` twice would
   * queue two writes against the same `searchParams` snapshot and the second
   * would overwrite the first.
   */
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

  async function askAgent(question: string) {
    const trimmed = question.trim();
    if (trimmed.length < 2 || agentLoading) return;
    setAgentLoading(true);
    setAgentError("");
    setAgentQuestion(trimmed);
    try {
      setAgent(await api.agent(trimmed, filters));
    } catch {
      setAgent(null);
      setAgentError("The assistant is unavailable while the local catalog preview is active.");
    } finally {
      setAgentLoading(false);
    }
  }

  function selectPreference(nextPreference: ShoppingPreference) {
    setPreference(nextPreference);
    void askAgent(nextPreference.question);
  }

  function toggleFilter(section: FilterSection) {
    setExpandedFilters((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  const catalogCategories = page?.facets.category_key ?? [];
  const fallbackProducts = showcaseCatalogPage({}).products;
  const recommendationPool = agent?.recommendations.length
    ? agent.recommendations
    : page?.products.length
      ? page.products
      : fallbackProducts;
  const recommendations = preferenceProducts(
    recommendationPool.some(preference.matches)
      ? recommendationPool
      : fallbackProducts,
    preference,
  );

  return (
    <div className="page mosaic-catalog-page">
      <div className="mosaic-catalog-layout">
        <aside className="catalog-sidebar">
          <header className="catalog-side-heading">
            <div>
              <p className="eyebrow">The Mosaic edit</p>
              <h1>Shop</h1>
            </div>
            <MosaicMark className="catalog-side-mark" />
            <p>
              {page ? `${page.total.toLocaleString()} curated pieces` : "Curated essentials"}
            </p>
          </header>
          <button
            className="mobile-filter-toggle"
            type="button"
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((current) => !current)}
          >
            <span><SlidersHorizontal size={17} /> Filters</span>
            <span>
              {activeFilterCount ? `${activeFilterCount} active` : "All products"}
              <ChevronDown size={16} />
            </span>
          </button>
          <aside className={filtersOpen ? "filter-panel open" : "filter-panel"}>
            <div className="filter-title">
              <h2>Filter collection</h2>
              {activeFilterCount ? <button type="button" onClick={clearFilters}>Clear all</button> : null}
            </div>
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("categories")} aria-expanded={expandedFilters.categories}>
                Categories {expandedFilters.categories ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilters.categories ? (
                <div className="filter-options">
                  <label>
                    <input type="radio" name="category" checked={!categoryKey} onChange={() => update("category_key")} />
                    <span>All products</span>
                    {page ? <small>{page.total.toLocaleString()}</small> : null}
                  </label>
                  {catalogCategories.slice(0, 6).map((item) => (
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
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("price")} aria-expanded={expandedFilters.price}>
                Price range {expandedFilters.price ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilters.price ? (
                <div className="price-range">
                  <div className="price-range-readout">
                    <span>${lowPrice.toLocaleString()}</span>
                    <span>
                      ${highPrice.toLocaleString()}
                      {highPrice >= priceCeiling ? "+" : ""}
                    </span>
                  </div>
                  {/* Two overlaid range inputs: the native control has no
                      two-thumb mode, and the track between the handles is drawn
                      from the same two values so it cannot drift out of sync. */}
                  <div
                    className="price-range-track"
                    style={{
                      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
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
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("availability")} aria-expanded={expandedFilters.availability}>
                Availability {expandedFilters.availability ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilters.availability ? (
                <div className="filter-options">
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
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("rating")} aria-expanded={expandedFilters.rating}>
                Customer rating {expandedFilters.rating ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilters.rating ? (
                <div className="rating-filter-options">
                  {ratingThresholds.map((threshold) => (
                    <label className="rating-filter-option" key={threshold}>
                      <input
                        type="radio"
                        name="min-rating"
                        checked={Number(minRating) === threshold}
                        onChange={() => update("min_rating", String(threshold))}
                      />
                      <span className="rating-filter-stars" aria-hidden="true">
                        {Array.from({ length: threshold }).map((_, index) => (
                          <Star key={index} size={13} fill="currentColor" />
                        ))}
                      </span>
                      <span className="rating-filter-note">&amp; up</span>
                    </label>
                  ))}
                  <label className="rating-filter-option">
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
          </aside>
        </aside>
        <section className="catalog-results">
          {/* Ask Mosaic leads the column: it is the primary affordance on this
              surface, and the sort control now sits with the result count it
              actually governs. */}
          <section className="catalog-agent" aria-label="Mosaic shopping assistant">
            <div className="catalog-agent-identity">
              <Sparkles size={20} aria-hidden="true" />
              <span>
                <strong>Ask Mosaic</strong>
                <small>Agentic hybrid retrieval</small>
              </span>
            </div>
            <SearchComposer
              compact
              pending={agentLoading}
              submitLabel="Ask"
              placeholder="Describe what would work best for you"
              onSubmit={(query) => void askAgent(query)}
            />
          </section>

          <nav className="category-pills" aria-label="Product categories">
            <button
              type="button"
              className={!categoryKey ? "active" : ""}
              onClick={() => update("category_key")}
            >
              All products
            </button>
            {catalogCategories.slice(0, 6).map((item) => (
              <button
                type="button"
                className={categoryKey === item.value ? "active" : ""}
                key={item.value}
                onClick={() => update("category_key", item.value)}
              >
                {formatCategoryKey(item.value)}
              </button>
            ))}
          </nav>

          <div className="results-toolbar">
            <p>
              {page ? (
                <>Showing <strong>{offset + 1}-{Math.min(offset + pageSize, page.total)}</strong> of {page.total.toLocaleString()} products</>
              ) : "Loading catalog"}
            </p>
            <div className="catalog-result-controls">
              <label className="catalog-sort">
                <span className="sr-only">Sort catalog</span>
                <select value={sort} onChange={(event) => update("sort", event.target.value)}>
                  <option value="featured">Sort by: Featured</option>
                  <option value="rating">Sort by: Rating</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                  <option value="newest">Sort by: Newest</option>
                </select>
              </label>
              <div className="catalog-view-control" role="group" aria-label="Catalog layout">
                <button
                  type="button"
                  className={catalogView === "grid" ? "active" : ""}
                  aria-pressed={catalogView === "grid"}
                  aria-label="Grid layout"
                  title="Grid layout"
                  onClick={() => setCatalogView("grid")}
                >
                  <Grid2X2 size={17} />
                </button>
                <button
                  type="button"
                  className={catalogView === "list" ? "active" : ""}
                  aria-pressed={catalogView === "list"}
                  aria-label="List layout"
                  title="List layout"
                  onClick={() => setCatalogView("list")}
                >
                  <List size={18} />
                </button>
              </div>
            </div>
          </div>

          {loading ? <LoadingState label="Loading products" /> : null}
          {error ? <ErrorState message={error} onRetry={load} /> : null}
          {!loading && !error && page ? (
            <div className="catalog-body">
              <div>
                <div className={catalogView === "grid" ? "product-grid" : "product-grid product-grid-list"}>
                  {page.products.map((product) => <ProductCard key={product.product_id} product={product} variant="catalog" />)}
                </div>
                <div className="pagination">
                  <button
                    type="button"
                    disabled={offset === 0}
                    onClick={() => update("offset", String(Math.max(0, offset - pageSize)), false)}
                  >
                    <ChevronLeft size={17} /> Previous
                  </button>
                  <span>{offset + 1}-{Math.min(offset + pageSize, page.total)} of {page.total.toLocaleString()}</span>
                  <button
                    type="button"
                    disabled={offset + pageSize >= page.total}
                    onClick={() => update("offset", String(offset + pageSize), false)}
                  >
                    Next <ChevronRight size={17} />
                  </button>
                </div>
              </div>

              <aside className="catalog-rail" aria-label="Recommended for you">
                <div className="catalog-rail-card">
                  <header>
                    <Sparkles size={18} aria-hidden="true" />
                    <span>
                      <strong>{agent ? "Mosaic's shortlist" : "Curated for you"}</strong>
                      <small>
                        {agent ? agentQuestion : `Matched to your ${preference.label.toLowerCase()} routine`}
                      </small>
                    </span>
                  </header>

                  <div className="catalog-rail-preferences" role="group" aria-label="Choose a shopping preference">
                    {shoppingPreferences.map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        className={preference.id === option.id ? "active" : ""}
                        aria-pressed={preference.id === option.id}
                        onClick={() => selectPreference(option)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>

                  {agentError ? <p className="catalog-rail-note" role="status">{agentError}</p> : null}
                  {agent ? <p className="catalog-rail-answer" aria-live="polite">{agent.answer}</p> : null}

                  <ul className="catalog-rail-list">
                    {recommendations.map((product, index) => (
                      <li key={`recommendation-${product.product_id}`}>
                        <Link href={`/products/${product.product_id}`}>
                          <img src={productImage(product)} alt="" width={64} height={64} />
                          <span>
                            <em>{String(index + 1).padStart(2, "0")}</em>
                            <strong>{product.model}</strong>
                            <small>{leafCategory(product.category_path)}</small>
                            <b>{formatPriceCompact(product.price_cents, product.currency)}</b>
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>

                  <p className="catalog-rail-foot">
                    Ranked by the same hybrid retrieval that answers Ask Mosaic.
                  </p>
                </div>
              </aside>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
