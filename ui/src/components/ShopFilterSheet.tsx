import { ChevronDown, ChevronUp, Star, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { CSSProperties, Ref } from "react";
import { EASE_OUT } from "../motion";
import { formatCategoryKey } from "../format";
import type { Availability } from "../types";

export type FilterSection = "categories" | "brand" | "price" | "availability" | "rating";

const ratingThresholds = [5, 4, 3, 2, 1] as const;

const availabilityOptions: Array<{ value: Availability | ""; label: string }> = [
  { value: "", label: "All availability" },
  { value: "in_stock", label: "In stock" },
  { value: "low_stock", label: "Low stock" },
  { value: "preorder", label: "Pre-order" },
];

interface FacetOption {
  value: string;
  count: number;
}

export interface ShopFilterSheetProps {
  open: boolean;
  onClose: () => void;
  sheetRef: Ref<HTMLElement>;
  reduceMotion: boolean;
  expandedFilters: Record<FilterSection, boolean>;
  onToggleSection: (section: FilterSection) => void;
  /** Mirrors Shop's own `update(name, value)`; every control here calls it. */
  onUpdate: (name: string, value?: string) => void;
  onClearAll: () => void;
  totalProductCount?: number;
  categoryKey?: string;
  catalogCategories: FacetOption[];
  brand?: string;
  catalogBrands: FacetOption[];
  /** The real catalog has no price or availability data to filter on. */
  showPriceAndAvailability: boolean;
  lowPrice: number;
  highPrice: number;
  priceCeiling: number;
  priceStep: number;
  onPriceChange: (low: number, high: number) => void;
  /** Commits the debounced price draft immediately, on handle release. */
  onPriceCommit: () => void;
  availability?: Availability;
  minRating?: string | null;
}

/**
 * The full-filter sheet: category, brand, price, availability, and rating,
 * one accordion each. `CatalogPage` owns the filter values themselves (they
 * are the URL's search params) and the focus trap that watches `sheetRef`;
 * this component only renders the accordions and reports intent through
 * `onUpdate`, the same generic setter Shop's own chip row calls.
 */
export function ShopFilterSheet({
  open,
  onClose,
  sheetRef,
  reduceMotion,
  expandedFilters,
  onToggleSection,
  onUpdate,
  onClearAll,
  totalProductCount,
  categoryKey,
  catalogCategories,
  brand,
  catalogBrands,
  showPriceAndAvailability,
  lowPrice,
  highPrice,
  priceCeiling,
  priceStep,
  onPriceChange,
  onPriceCommit,
  availability,
  minRating,
}: ShopFilterSheetProps) {
  return (
    <AnimatePresence initial={false}>
      {open ? (
        <div className="shop-filter-layer">
          <motion.button
            className="shop-filter-backdrop"
            type="button"
            aria-label="Close filters"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.1 : 0.18 }}
          />
          <motion.aside
            ref={sheetRef}
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
              <button type="button" aria-label="Close filters" onClick={onClose}>
                <X size={20} />
              </button>
            </header>

            <div className="shop-filter-body">
              <section className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => onToggleSection("categories")}
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
                        onChange={() => onUpdate("category_key")}
                      />
                      <span>All products</span>
                      {totalProductCount !== undefined ? <small>{totalProductCount.toLocaleString()}</small> : null}
                    </label>
                    {catalogCategories.slice(0, 8).map((item) => (
                      <label key={item.value}>
                        <input
                          type="radio"
                          name="category"
                          checked={categoryKey === item.value}
                          onChange={() => onUpdate("category_key", item.value)}
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
                  onClick={() => onToggleSection("brand")}
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
                        onChange={() => onUpdate("brand")}
                      />
                      <span>All brands</span>
                    </label>
                    {catalogBrands.slice(0, 10).map((item) => (
                      <label key={item.value}>
                        <input
                          type="radio"
                          name="brand"
                          checked={brand === item.value}
                          onChange={() => onUpdate("brand", item.value)}
                        />
                        <span>{item.value}</span>
                        <small>{item.count.toLocaleString()}</small>
                      </label>
                    ))}
                  </div>
                ) : null}
              </section>

              <section hidden={!showPriceAndAvailability} className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => onToggleSection("price")}
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
                        onChange={(event) => onPriceChange(Number(event.target.value), highPrice)}
                        onPointerUp={onPriceCommit}
                        onKeyUp={onPriceCommit}
                      />
                      <input
                        type="range"
                        aria-label="Maximum price"
                        min={0}
                        max={priceCeiling}
                        step={priceStep}
                        value={highPrice}
                        onChange={(event) => onPriceChange(lowPrice, Number(event.target.value))}
                        onPointerUp={onPriceCommit}
                        onKeyUp={onPriceCommit}
                      />
                    </div>
                  </div>
                ) : null}
              </section>

              <section hidden={!showPriceAndAvailability} className="shop-filter-section">
                <button
                  type="button"
                  onClick={() => onToggleSection("availability")}
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
                          onChange={() => onUpdate("availability", option.value || undefined)}
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
                  onClick={() => onToggleSection("rating")}
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
                          onChange={() => onUpdate("min_rating", String(threshold))}
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
                        onChange={() => onUpdate("min_rating")}
                      />
                      <span>Any rating</span>
                    </label>
                  </div>
                ) : null}
              </section>
            </div>

            <footer>
              <button type="button" onClick={onClearAll}>Clear all</button>
              <button className="primary" type="button" onClick={onClose}>
                Done
              </button>
            </footer>
          </motion.aside>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
