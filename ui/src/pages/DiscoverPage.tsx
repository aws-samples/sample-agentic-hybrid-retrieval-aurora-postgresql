import { ArrowRight, Search, Sparkles } from "lucide-react";
import { FormEvent, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { ProductCard } from "../components/ProductCard";
import { productImageMap } from "../media";
import { useNavigate } from "../navigation";
import { showcaseCatalogPage } from "../showcase";
import type { SearchFilters } from "../types";

type StarterQuery = {
  topic: string;
  title: string;
  caption: string;
  query: string;
  image: string;
  imageFit?: "cover";
  filters: Pick<SearchFilters, "domain" | "category_key">;
};

const starterQueries: StarterQuery[] = [
  {
    topic: "Workspace",
    title: "The Quiet Office",
    caption: "Focus, refined.",
    query: "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.",
    image: "/assets/images/mosaic/category/workspace.webp",
    filters: {
      domain: "home_office",
      category_key: "ergonomic-office-chairs",
    },
  },
  {
    topic: "Performance",
    title: "Built for Distance",
    caption: "Cushioning, speed, balance.",
    query: "Road-running marathon shoes with a carbon plate and maximum cushioning",
    image: "/assets/images/mosaic/stride-pro-studio.webp",
    imageFit: "cover",
    filters: {
      domain: "running_fitness",
      category_key: "road-running-shoes",
    },
  },
  {
    topic: "Travel",
    title: "Fourteen Hours, First Class",
    caption: "Comfort that outlasts the flight.",
    query: "Comfortable over-ear headphones for a 14-hour flight",
    image: "/assets/images/mosaic/category/audio.webp",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
];

const labStages = [
  {
    number: "01",
    stage: "Retrieve",
    title: "Build hybrid retrieval",
    caption: "Lexical, fuzzy, and semantic arms over one Aurora catalog.",
    graphic: "retrieve" as const,
  },
  {
    number: "02",
    stage: "Rank",
    title: "Fuse, rerank, and explain",
    caption: "Watch candidates move as fusion and reranking take over.",
    graphic: "rank" as const,
  },
  {
    number: "03",
    stage: "Reason",
    title: "Build the retrieval agent",
    caption: "Give the system you built to an agent that cites its evidence.",
    graphic: "reason" as const,
  },
];

// Discover is an editorial entry surface, not a live-search result. Loading
// these fixed premium-cohort cards locally prevents the Shop band from
// appearing a second after the rest of the page, while Shop remains the
// authoritative live catalog and retrieval surface.
const featuredPreview = showcaseCatalogPage({}, 0, 4, "featured").products;

function LabGraphic({ variant }: { variant: "retrieve" | "rank" | "reason" }) {
  if (variant === "retrieve") {
    return (
      <span className="discover-lab-scene discover-lab-scene-retrieve" aria-hidden="true">
        <img
          className="discover-lab-scene-photo"
          src="/assets/images/mosaic/ho-quiet-keyboards-01-catalog-3x2.webp"
          alt=""
          loading="lazy"
          decoding="async"
        />
        <span className="discover-lab-query-pill">
          <Search size={14} />
          quiet mechanical keyboard
        </span>
        <span className="discover-lab-candidate discover-lab-candidate-one">
          <img
            src="/assets/images/mosaic/ho-quiet-keyboards-02-catalog-3x2.webp"
            alt=""
            loading="lazy"
            decoding="async"
          />
        </span>
        <span className="discover-lab-candidate discover-lab-candidate-two">
          <img
            src="/assets/images/mosaic/ho-ergonomic-keyboards-catalog-3x2.webp"
            alt=""
            loading="lazy"
            decoding="async"
          />
        </span>
        <span className="discover-lab-channel-strip">
          <span>FTS</span>
          <span>pg_trgm</span>
          <span>pgvector</span>
        </span>
      </span>
    );
  }

  if (variant === "rank") {
    return (
      <span className="discover-lab-scene discover-lab-scene-rank" aria-hidden="true">
        <span className="discover-lab-scene-label">Reranked shortlist</span>
        <span className="discover-lab-rank-products">
          <span className="discover-lab-rank-product discover-lab-rank-product-two">
            <b>02</b>
            <img
              src="/assets/images/mosaic/ho-ergonomic-office-chairs-02-catalog-3x2.webp"
              alt=""
              loading="lazy"
              decoding="async"
            />
          </span>
          <span className="discover-lab-rank-product discover-lab-rank-product-one">
            <b>01</b>
            <img
              src="/assets/images/mosaic/ho-ergonomic-office-chairs-forma-ergonomic-catalog-3x2.webp"
              alt=""
              loading="lazy"
              decoding="async"
            />
          </span>
          <span className="discover-lab-rank-product discover-lab-rank-product-three">
            <b>03</b>
            <img
              src="/assets/images/mosaic/ho-ergonomic-office-chairs-03-catalog-3x2.webp"
              alt=""
              loading="lazy"
              decoding="async"
            />
          </span>
        </span>
        <span className="discover-lab-rank-receipt">
          <span>RRF</span>
          <ArrowRight size={14} />
          <strong>model rerank</strong>
        </span>
      </span>
    );
  }

  return (
    <span className="discover-lab-scene discover-lab-scene-reason" aria-hidden="true">
      <img
        className="discover-lab-scene-photo"
        src="/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp"
        alt=""
        loading="lazy"
        decoding="async"
      />
      <span className="discover-lab-evidence">
        <small>Evidence retrieved</small>
        <strong>Auraluxe H9</strong>
        <span>
          Adaptive noise cancellation <b>[1]</b>
        </span>
        <span>
          Up to 60 hours <b>[2]</b>
        </span>
        <em>Grounded recommendation</em>
      </span>
    </span>
  );
}

export function DiscoverPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const previewImages = useMemo(() => productImageMap(featuredPreview), []);
  const searchRef = useRef<HTMLInputElement>(null);

  function search(
    nextQuery: string,
    filters: Pick<SearchFilters, "domain" | "category_key"> = {},
  ) {
    const params = new URLSearchParams({ q: nextQuery });
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.category_key) params.set("category_key", filters.category_key);
    navigate(`/catalog?${params}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length >= 2) search(trimmed);
  }

  function askMosaic() {
    const params = new URLSearchParams({ ask: "1" });
    const trimmed = query.trim();
    if (trimmed.length >= 2) params.set("q", trimmed);
    navigate(`/catalog?${params}`);
  }

  function focusSearch() {
    searchRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    searchRef.current?.focus({ preventScroll: true });
  }

  return (
    <div className="discover-experience">
      <section className="discover-hero">
        <picture className="discover-backdrop">
          <source
            media="(max-width: 640px)"
            srcSet="/assets/images/mosaic/hero-landing-scene.webp"
            width={1568}
            height={1908}
          />
          <img
            src="/assets/images/mosaic/hero-landing-wide.webp"
            alt="A sunlit travertine desk with cream over-ear headphones, a fabric speaker, a tablet, earbuds, and a keyboard"
            width={1672}
            height={941}
          />
        </picture>
        <div className="discover-scrim" aria-hidden="true" />
        <div className="discover-hero-content">
          <p className="discover-hero-kicker">The Mosaic edit</p>
          <h1>
            <span>Objects that shape</span>
            <em>your world.</em>
          </h1>
          <p className="discover-hero-sub">
            Curated spaces. Considered choices. Intelligent finds.
          </p>
          <div className="discover-hero-actions">
            <button type="button" onClick={focusSearch}>
              Search the catalog
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      </section>

      <div className="discover-body">
        <section className="discover-section" aria-labelledby="discover-search-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-search-title">Try asking Mosaic</h2>
              <p>Start with one of these three example searches.</p>
            </div>
          </header>
          <form className="discover-search" onSubmit={submit} role="search">
            <GenerativeSearchIcon size={20} />
            <input
              ref={searchRef}
              aria-label="Search products"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search for anything, in your own words"
              minLength={2}
            />
            {/* The label carries the button at desktop width; below 640px the
                arrow replaces it so Search and Ask Mosaic no longer stack into
                three rows. aria-label keeps the accessible name identical in
                both states. */}
            <button className="discover-search-submit" type="submit" aria-label="Search Mosaic">
              <span>Search</span>
              <ArrowRight className="discover-search-submit-icon" size={18} aria-hidden="true" />
            </button>
            <button
              className="discover-search-ask"
              type="button"
              onClick={askMosaic}
              aria-label="Ask Mosaic"
            >
              <Sparkles size={15} aria-hidden="true" />
              Ask Mosaic
            </button>
          </form>
          <div className="discover-editorial-grid">
            {starterQueries.map((starter) => (
              <button
                key={starter.topic}
                className="discover-editorial-card"
                type="button"
                onClick={() => search(starter.query, starter.filters)}
                aria-label={starter.query}
              >
                <span
                  className={
                    starter.imageFit === "cover"
                      ? "discover-editorial-media is-cover"
                      : "discover-editorial-media"
                  }
                >
                  <img src={starter.image} alt="" loading="lazy" decoding="async" />
                </span>
                <span className="discover-editorial-body">
                  <small>{starter.topic}</small>
                  <strong>{starter.title}</strong>
                  <em>“{starter.query}”</em>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="discover-section" aria-labelledby="discover-shop-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-shop-title">Shop</h2>
              <p>Thoughtfully designed. Expertly made.</p>
            </div>
            <Link className="discover-section-link" href="/catalog">
              Shop all
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </header>
          <div className="discover-plate">
            <span className="discover-plate-media">
              <img
                src="/assets/images/mosaic/editorial-fitness-wide.webp"
                alt="A maroon kettlebell, dumbbells, cushioned running shoes, a rolled mat, an insulated bottle, and a fitness watch on travertine blocks"
                loading="lazy"
                decoding="async"
                width={1672}
                height={941}
              />
            </span>
            <div className="discover-plate-copy">
              <small>Running &amp; fitness</small>
              <strong>Built for the long run.</strong>
              <p>
                Browse the 120-product edit, or describe your run to retrieve
                from all 500,000 products.
              </p>
              <Link className="discover-plate-link" href="/catalog?domain=running_fitness">
                Shop running &amp; fitness
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </div>
          </div>
          <div className="discover-shop-grid">
            {featuredPreview.map((product) => (
              <ProductCard
                key={product.product_id}
                product={product}
                imageSrc={previewImages.get(product.product_id)}
                variant="catalog"
              />
            ))}
          </div>
        </section>

        <section className="discover-section discover-labs" aria-labelledby="discover-labs-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-labs-title">Mosaic Labs</h2>
              <p>See how Mosaic retrieves candidates, ranks results, and grounds recommendations.</p>
            </div>
            <Link className="discover-section-link solid" href="/mosaic-labs">
              Launch labs
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </header>
          <div className="discover-labs-grid">
            {labStages.map((lab) => (
              <Link className="discover-lab-card" key={lab.stage} href="/mosaic-labs">
                <span className="discover-lab-graphic">
                  <LabGraphic variant={lab.graphic} />
                </span>
                <span className="discover-lab-copy">
                  <small>
                    {lab.number} · {lab.stage}
                  </small>
                  <strong>{lab.title}</strong>
                  <em>{lab.caption}</em>
                </span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
