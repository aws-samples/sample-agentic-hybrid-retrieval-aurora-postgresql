import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Sparkles,
  SlidersHorizontal,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { MosaicMark } from "../components/MosaicMark";
import { ProductCard } from "../components/ProductCard";
import { SearchComposer } from "../components/SearchComposer";
import { ErrorState, LoadingState } from "../components/States";
import { useNavigate, useSearchParams } from "../navigation";
import { showcaseCatalogPage } from "../showcase";
import type { AgentResponse, CatalogPage, Domain, ProductSummary, SearchFilters } from "../types";

const pageSize = 24;

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
    matches: (product) => product.category === "Audio",
  },
  {
    id: "travel",
    label: "Travel",
    question: "Recommend compact, versatile essentials for working on the move.",
    matches: (product) =>
      product.category === "Accessories" ||
      product.subcategory === "Wireless Earbuds" ||
      product.subcategory === "Over-Ear Headphones",
  },
];

function preferenceProducts(products: ProductSummary[], preference: ShoppingPreference) {
  const matching = products.filter(preference.matches);
  return (matching.length ? matching : products).slice(0, 3);
}

export function CatalogPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expandedFilter, setExpandedFilter] = useState<
    "categories" | "price" | "availability" | "rating" | null
  >("categories");
  const [preference, setPreference] = useState<ShoppingPreference>(shoppingPreferences[0]);
  const [agent, setAgent] = useState<AgentResponse | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState("");
  const [agentQuestion, setAgentQuestion] = useState("");
  const domain = (searchParams.get("domain") || undefined) as Domain | undefined;
  const offset = Number(searchParams.get("offset") ?? 0);
  const sort = searchParams.get("sort") ?? "featured";
  const availability = searchParams.get("availability") || undefined;
  const minRating = searchParams.get("min_rating");
  const category = searchParams.get("category") || undefined;
  const brand = searchParams.get("brand") || undefined;
  const minPrice = searchParams.get("min_price");
  const maxPrice = searchParams.get("max_price");
  const filters: SearchFilters = {
    domain,
    category,
    brand,
    availability: availability as SearchFilters["availability"],
    min_rating: minRating ? Number(minRating) : undefined,
    min_price: minPrice ? Number(minPrice) : undefined,
    max_price: maxPrice ? Number(maxPrice) : undefined,
  };
  const activeFilterCount = [
    domain,
    category,
    brand,
    availability,
    minRating,
    minPrice,
    maxPrice,
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
  }, [domain, category, brand, availability, minRating, minPrice, maxPrice, offset, sort]);

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

  function toggleFilter(
    section: "categories" | "price" | "availability" | "rating",
  ) {
    setExpandedFilter((current) => current === section ? null : section);
  }

  const catalogCategories = page?.facets.category ?? [];
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
              <button type="button" onClick={() => toggleFilter("categories")} aria-expanded={expandedFilter === "categories"}>
                Categories {expandedFilter === "categories" ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilter === "categories" ? (
                <div className="filter-options">
                  <label>
                    <input type="radio" checked={!category} onChange={() => update("category")} />
                    <span>All products</span>
                    {page ? <small>{page.total.toLocaleString()}</small> : null}
                  </label>
                  {catalogCategories.slice(0, 6).map((item) => (
                    <label key={item.value}>
                      <input
                        type="radio"
                        checked={category === item.value}
                        onChange={() => update("category", item.value)}
                      />
                      <span>{item.value}</span>
                      <small>{item.count.toLocaleString()}</small>
                    </label>
                  ))}
                </div>
              ) : null}
            </section>
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("price")} aria-expanded={expandedFilter === "price"}>
                Price range {expandedFilter === "price" ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilter === "price" ? (
                <div className="price-filter">
                  <label>
                    <span className="sr-only">Minimum price</span>
                    <input
                      type="number"
                      min="0"
                      placeholder="Min"
                      value={minPrice ?? ""}
                      onChange={(event) => update("min_price", event.target.value)}
                    />
                  </label>
                  <span>to</span>
                  <label>
                    <span className="sr-only">Maximum price</span>
                    <input
                      type="number"
                      min="0"
                      placeholder="Max"
                      value={maxPrice ?? ""}
                      onChange={(event) => update("max_price", event.target.value)}
                    />
                  </label>
                </div>
              ) : null}
            </section>
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("availability")} aria-expanded={expandedFilter === "availability"}>
                Availability {expandedFilter === "availability" ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilter === "availability" ? (
                <div className="filter-options">
                  <label>
                    <input
                      type="checkbox"
                      checked={availability === "In Stock"}
                      onChange={(event) => update("availability", event.target.checked ? "In Stock" : undefined)}
                    />
                    In stock
                  </label>
                </div>
              ) : null}
            </section>
            <section className="catalog-filter-section">
              <button type="button" onClick={() => toggleFilter("rating")} aria-expanded={expandedFilter === "rating"}>
                Rating {expandedFilter === "rating" ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFilter === "rating" ? (
                <select value={minRating ?? ""} onChange={(event) => update("min_rating", event.target.value)}>
                  <option value="">Any rating</option>
                  <option value="4">4.0 and up</option>
                  <option value="4.5">4.5 and up</option>
                </select>
              ) : null}
            </section>
          </aside>
        </aside>
        <section className="catalog-results">
          <header className="catalog-toolbar">
            <SearchComposer
              compact
              placeholder="Search products..."
              onSubmit={(query) => navigate(`/search?q=${encodeURIComponent(query)}`)}
            />
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
          </header>
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
          <section className="catalog-preferences" aria-label="Shopping preferences">
            <span>Build your edit</span>
            <div role="group" aria-label="Choose a shopping preference">
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
          </section>
          {agentError ? <p className="catalog-agent-error" role="status">{agentError}</p> : null}
          {agent ? (
            <section className="catalog-agent-answer" aria-live="polite">
              <p className="eyebrow">Mosaic's take</p>
              <p>{agent.answer}</p>
            </section>
          ) : null}
          <section className="catalog-recommendations">
            <header>
              <div>
                <p className="eyebrow">Your edit</p>
                <h2>{agent ? "Mosaic's shortlist" : `For your ${preference.label.toLowerCase()} routine`}</h2>
              </div>
              <span>{agent ? agentQuestion : "Tailored to your current selection"}</span>
            </header>
            <div className="catalog-recommendation-grid">
              {recommendations.map((product) => (
                <ProductCard key={`recommendation-${product.product_id}`} product={product} variant="catalog" />
              ))}
            </div>
          </section>
          <nav className="category-pills" aria-label="Product categories">
            <button
              type="button"
              className={!category ? "active" : ""}
              onClick={() => update("category")}
            >
              All products
            </button>
            {catalogCategories.slice(0, 6).map((item) => (
              <button
                type="button"
                className={category === item.value ? "active" : ""}
                key={item.value}
                onClick={() => update("category", item.value)}
              >
                {item.value}
              </button>
            ))}
          </nav>
          <div className="results-toolbar">
            <p>
              {page ? (
                <>Showing <strong>{offset + 1}-{Math.min(offset + pageSize, page.total)}</strong> of {page.total.toLocaleString()} products</>
              ) : "Loading catalog"}
            </p>
          </div>
          {loading ? <LoadingState label="Loading products" /> : null}
          {error ? <ErrorState message={error} onRetry={load} /> : null}
          {!loading && !error && page ? (
            <>
              <div className="product-grid">
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
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}
