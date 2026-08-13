import { ArrowRight, Search, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { ProductCard } from "../components/ProductCard";
import { productImageMap } from "../media";
import { useNavigate } from "../navigation";
import type { ProductSummary, SearchFilters } from "../types";

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
    graphic: "scatter" as const,
  },
  {
    number: "02",
    stage: "Rank",
    title: "Fuse, rerank, and explain",
    caption: "Watch candidates move as fusion and reranking take over.",
    graphic: "waves" as const,
  },
  {
    number: "03",
    stage: "Reason",
    title: "Build the retrieval agent",
    caption: "Give the system you built to an agent that cites its evidence.",
    graphic: "graph" as const,
  },
];

function LabGraphic({ variant }: { variant: "scatter" | "waves" | "graph" }) {
  if (variant === "scatter") {
    const points = [
      [14, 44], [22, 30], [30, 50], [38, 22], [46, 38], [54, 12],
      [62, 42], [70, 26], [78, 48], [86, 18], [94, 34], [26, 14],
      [58, 54], [82, 8], [18, 58], [42, 56], [66, 10], [90, 52],
    ];
    return (
      <svg viewBox="0 0 108 66" aria-hidden="true">
        {points.map(([x, y], index) => (
          <circle
            key={`${x}-${y}`}
            cx={x}
            cy={y}
            r={index % 4 === 0 ? 2.4 : 1.5}
            fill={index % 3 === 0 ? "var(--maroon-700)" : "var(--gold)"}
            opacity={index % 2 === 0 ? 0.85 : 0.45}
          />
        ))}
      </svg>
    );
  }
  if (variant === "waves") {
    return (
      <svg viewBox="0 0 108 66" aria-hidden="true" fill="none">
        <path d="M4 50 C 24 50, 30 18, 54 18 S 84 44, 104 44" stroke="var(--maroon-700)" strokeWidth="1.8" />
        <path d="M4 34 C 24 34, 34 42, 54 30 S 84 14, 104 22" stroke="var(--gold)" strokeWidth="1.4" opacity="0.8" />
        <path d="M4 18 C 28 18, 36 54, 58 48 S 88 56, 104 58" stroke="var(--line-dark)" strokeWidth="1.2" opacity="0.9" />
        <circle cx="54" cy="18" r="3" fill="var(--maroon-700)" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 108 66" aria-hidden="true" fill="none">
      <path
        d="M18 50 L 42 32 L 70 40 L 90 16 M 42 32 L 54 12 M 70 40 L 70 58"
        stroke="var(--line-dark)"
        strokeWidth="1.3"
      />
      <circle cx="18" cy="50" r="3.4" fill="var(--gold)" />
      <circle cx="42" cy="32" r="4.2" fill="var(--maroon-700)" />
      <circle cx="54" cy="12" r="2.8" fill="var(--gold)" />
      <circle cx="70" cy="40" r="3.4" fill="var(--maroon-700)" opacity="0.75" />
      <circle cx="70" cy="58" r="2.4" fill="var(--line-dark)" />
      <circle cx="90" cy="16" r="3" fill="var(--gold)" />
    </svg>
  );
}

export function DiscoverPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<ProductSummary[]>([]);
  const [previewError, setPreviewError] = useState("");
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const previewImages = useMemo(() => productImageMap(preview), [preview]);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .catalog({}, 0, 4, "featured")
      .then((page) => {
        if (!cancelled) {
          setPreview(page.products.slice(0, 4));
          setPreviewError("");
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setPreview([]);
          setPreviewError(
            cause instanceof Error
              ? cause.message
              : "Featured products are unavailable",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
              Explore collections
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
              <p>Three considered starting points.</p>
            </div>
          </header>
          <form className="discover-search" onSubmit={submit} role="search">
            <Search size={20} aria-hidden="true" />
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

        {preview.length ? (
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
              {preview.map((product) => (
                <ProductCard
                  key={product.product_id}
                  product={product}
                  imageSrc={previewImages.get(product.product_id)}
                  variant="catalog"
                />
              ))}
            </div>
          </section>
        ) : previewError ? (
          <section className="discover-section" aria-labelledby="discover-shop-title">
            <header className="discover-section-heading">
              <div>
                <h2 id="discover-shop-title">Shop</h2>
                <p role="alert">Featured products are unavailable: {previewError}</p>
              </div>
            </header>
          </section>
        ) : null}

        <section className="discover-section discover-labs" aria-labelledby="discover-labs-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-labs-title">Mosaic Labs</h2>
              <p>The same storefront with the hood open. DAT410 builder’s session.</p>
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
                <small>
                  {lab.number} · {lab.stage}
                </small>
                <strong>{lab.title}</strong>
                <em>{lab.caption}</em>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
