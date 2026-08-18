import { ArrowRight, Search, Sparkles } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "wouter";
import {
  CatalogSearchComposer,
  catalogGhostQueries,
} from "../components/CatalogSearchComposer";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { ProductCard } from "../components/ProductCard";
import { productImageMap } from "../media";
import { useNavigate } from "../navigation";
import { showcaseCatalogPage } from "../showcase";
import type { SearchFilters } from "../types";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

type StarterQuery = {
  topic: string;
  title: string;
  caption: string;
  /** The hero chip label. It is also the query the chip runs, verbatim. */
  prompt: string;
  query: string;
  image: string;
  imageFit?: "cover";
  mode?: "search" | "ask";
  filters: Pick<SearchFilters, "domain" | "category_key">;
};

const starterQueries: StarterQuery[] = [
  {
    // The card prints "Featured · {topic}", so this used to read
    // "Featured · Featured". The topic is the category the prompt actually
    // constrains to, and the photograph is the catalog plate for product 2
    // (Sonora WH-C720) in that same category rather than a generic audio plate.
    topic: "Over-Ear Headphones",
    title: "Find the best over-ear headphones for focus and travel",
    caption: "Comfort, focus, and travel priorities in one request.",
    prompt: "Best noise-cancelling headphones",
    query: "Find the best over-ear headphones for focus and travel.",
    image: "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    // The catalog plates are 3:2 and the frame is 4:5, so this one fills the
    // frame rather than sitting letterboxed inside it. The other two starters
    // are portrait crops that already fit.
    imageFit: "cover",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
  {
    topic: "Preferences",
    title: "Recommendations that get you",
    caption: "Fit, budget, and must-haves become explicit catalog constraints.",
    prompt: "Ergonomic chair for long workdays",
    query: "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.",
    image: "/assets/images/mosaic/category/workspace.webp",
    filters: {
      domain: "home_office",
      category_key: "ergonomic-office-chairs",
    },
  },
  {
    topic: "Evidence",
    title: "Grounded answers. No guesswork.",
    caption: "Compare catalog facts and inspect the evidence behind each pick.",
    prompt: "Headphones for a long flight",
    query: "Comfortable over-ear headphones for a 14-hour flight",
    image: "/assets/images/mosaic/category/audio.webp",
    mode: "ask",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
];

const heroPrompts = [
  {
    label: "Best noise-cancelling headphones",
    query: "Best noise-cancelling headphones",
    filters: starterQueries[0].filters,
  },
  {
    label: "Ergonomic office chair",
    query: "Ergonomic chair for long workdays",
    filters: starterQueries[1].filters,
  },
  {
    label: "Headphones for a long flight",
    query: "Headphones for a long flight",
    filters: starterQueries[2].filters,
  },
  {
    label: "Sonora WH-C720",
    query: "Sonora WH-C720",
    filters: {} as Pick<SearchFilters, "domain" | "category_key">,
  },
  {
    label: "Auraluxe H9",
    query: "Auraluxe H9",
    filters: {} as Pick<SearchFilters, "domain" | "category_key">,
  },
  {
    label: "Carbon-plated shoes",
    query: "Carbon-plated marathon shoes",
    filters: {} as Pick<SearchFilters, "domain" | "category_key">,
  },
];

/**
 * Browse entries for the category rail.
 *
 * Every tile is a real `category_key` the catalog filters on, illustrated by
 * that category's own commissioned plate rather than by a product photograph
 * borrowed from a neighbouring category. Deliberately no product counts: the
 * only counts that would be true here are the facet counts Shop reads back
 * from the API, and Discover does not make that request.
 */
const intentionCategories = [
  {
    label: "Over-ear headphones",
    domain: "consumer_electronics",
    categoryKey: "over-ear-headphones",
    image: "/assets/images/mosaic/ce-over-ear-headphones-plate-01-catalog-3x2.webp",
  },
  {
    label: "Quiet keyboards",
    domain: "home_office",
    categoryKey: "quiet-keyboards",
    image: "/assets/images/mosaic/ho-quiet-keyboards-plate-01-catalog-3x2.webp",
  },
  {
    label: "Ergonomic chairs",
    domain: "home_office",
    categoryKey: "ergonomic-office-chairs",
    image: "/assets/images/mosaic/ho-ergonomic-office-chairs-plate-01-catalog-3x2.webp",
  },
  {
    label: "Road-running shoes",
    domain: "running_fitness",
    categoryKey: "road-running-shoes",
    image: "/assets/images/mosaic/rf-road-running-shoes-plate-01-catalog-3x2.webp",
  },
  {
    label: "Standing desks",
    domain: "home_office",
    categoryKey: "electric-standing-desks",
    image: "/assets/images/mosaic/ho-electric-standing-desks-plate-01-catalog-3x2.webp",
  },
  {
    label: "Charging docks",
    domain: "consumer_electronics",
    categoryKey: "charging-docks",
    image: "/assets/images/mosaic/ce-charging-docks-plate-01-catalog-3x2.webp",
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
          quiet keyboard
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

/**
 * The signal figure behind the Labs band.
 *
 * Three strands converge into one and hand off to the photographs on the right,
 * which is the shape of the thing the labs teach: a lexical, a fuzzy, and a
 * semantic arm fused into a single ranked list. Decorative, so it carries no
 * numbers - the measured values live on the Labs surface itself.
 */
function LabsSignal() {
  return (
    <span className="discover-labs-signal" aria-hidden="true">
      <svg viewBox="0 0 480 420" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id="discover-labs-strand" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#b3833f" stopOpacity="0" />
            <stop offset="44%" stopColor="#c9954c" stopOpacity="0.5" />
            <stop offset="86%" stopColor="#f2d5a4" stopOpacity="0.92" />
            <stop offset="100%" stopColor="#f2d5a4" stopOpacity="0.34" />
          </linearGradient>
          <radialGradient id="discover-labs-bloom" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0%" stopColor="#f2d5a4" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#f2d5a4" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="392" cy="284" fill="url(#discover-labs-bloom)" rx="200" ry="164" />
        <g fill="none" stroke="url(#discover-labs-strand)" strokeLinecap="round">
          <path d="M-40 178 C 120 178 232 240 400 284" strokeWidth="17" />
          <path d="M-40 284 C 140 284 250 284 400 284" strokeWidth="27" />
          <path d="M-40 392 C 120 392 232 330 400 284" strokeWidth="17" />
        </g>
      </svg>
    </span>
  );
}

export function DiscoverPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const previewImages = useMemo(() => productImageMap(featuredPreview), []);
  const reduceMotion = useReducedMotion() ?? false;
  const heroItem = (delay: number) => ({
    initial: reduceMotion
      ? { opacity: 0.84 }
      : { opacity: 0, y: 10, filter: "blur(5px)" },
    animate: reduceMotion
      ? { opacity: 1 }
      : { opacity: 1, y: 0, filter: "blur(0px)" },
    transition: reduceMotion
      ? { duration: 0.18 }
      : { duration: 0.56, delay, ease: EASE_OUT },
  });

  function search(
    nextQuery: string,
    filters: Pick<SearchFilters, "domain" | "category_key"> = {},
  ) {
    const params = new URLSearchParams({ q: nextQuery });
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.category_key) params.set("category_key", filters.category_key);
    navigate(`/catalog?${params}`);
  }

  function askMosaic(
    nextQuery = query,
    filters: Pick<SearchFilters, "domain" | "category_key"> = {},
  ) {
    const params = new URLSearchParams({ ask: "1" });
    const trimmed = nextQuery.trim();
    if (trimmed.length >= 2) params.set("q", trimmed);
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.category_key) params.set("category_key", filters.category_key);
    navigate(`/catalog?${params}`);
  }

  function runStarter(starter: StarterQuery) {
    if (starter.mode === "ask") {
      askMosaic(starter.query, starter.filters);
      return;
    }
    search(starter.query, starter.filters);
  }

  const [featuredStarter, ...secondaryStarters] = starterQueries;

  return (
    <div className="discover-experience">
      <section className="discover-hero">
        <motion.picture
          className="discover-backdrop"
          initial={
            reduceMotion
              ? { opacity: 0.88 }
              : { opacity: 0.78, scale: 1.025, clipPath: "inset(0 0 0 4%)" }
          }
          animate={
            reduceMotion
              ? { opacity: 1 }
              : { opacity: 1, scale: 1, clipPath: "inset(0 0 0 0%)" }
          }
          transition={
            reduceMotion
              ? { duration: 0.2 }
              : { duration: 0.8, ease: EASE_OUT }
          }
        >
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
        </motion.picture>
        <div className="discover-scrim" aria-hidden="true" />
        <div className="discover-hero-content">
          <motion.p className="discover-hero-kicker" {...heroItem(0.12)}>
            Intelligent shopping, elevated
          </motion.p>
          <h1>
            <motion.span {...heroItem(0.18)}>Objects that shape</motion.span>
            <motion.em {...heroItem(0.25)}>your world.</motion.em>
          </h1>
          <motion.p className="discover-hero-sub" {...heroItem(0.32)}>
            Ask in your own words, or search the way you always have. Mosaic
            retrieves from the catalog either way.
          </motion.p>
          <motion.div className="discover-search" role="search" {...heroItem(0.39)}>
            <CatalogSearchComposer
              idleSuggestions={catalogGhostQueries}
              inputLabel="Search products"
              leadingIcon={<GenerativeSearchIcon size={20} />}
              onSubmit={search}
              onValueChange={setQuery}
              placeholder="Ask anything, or search products"
              showSuggestions={false}
              suggestionsOnType={false}
            />
            <button
              className="discover-search-ask"
              type="button"
              onClick={() => askMosaic()}
              aria-label="Ask Mosaic"
            >
              <Sparkles size={15} aria-hidden="true" />
              Ask Mosaic
            </button>
          </motion.div>
          {/* Each chip searches for exactly the words on it. */}
          <motion.div className="discover-hero-prompts" {...heroItem(0.46)}>
            <span>Try asking</span>
            {heroPrompts.map((starter) => (
              <button
                key={starter.label}
                type="button"
                onClick={() => search(starter.query, starter.filters)}
              >
                {starter.label}
              </button>
            ))}
          </motion.div>
        </div>
      </section>

      <div className="discover-body">
        <section className="discover-section" aria-labelledby="discover-starters-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-starters-title">Start with a real need</h2>
              <p>
                Each of these three runs hybrid retrieval over the catalog, with
                its category constraint already applied.
              </p>
            </div>
          </header>
          <div className="discover-editorial-grid">
            <button
              className="discover-editorial-card is-featured"
              type="button"
              onClick={() => runStarter(featuredStarter)}
              aria-label={featuredStarter.query}
            >
              <span
                className={
                  featuredStarter.imageFit === "cover"
                    ? "discover-editorial-media is-cover"
                    : "discover-editorial-media"
                }
              >
                <img
                  src={featuredStarter.image}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
              </span>
              <span className="discover-editorial-body">
                <small>Featured · {featuredStarter.topic}</small>
                <strong>{featuredStarter.title}</strong>
                <em>“{featuredStarter.query}”</em>
                <span className="discover-editorial-run">
                  Try this prompt
                  <ArrowRight size={14} aria-hidden="true" />
                </span>
              </span>
            </button>
            {secondaryStarters.map((starter) => (
              <button
                key={starter.topic}
                className="discover-editorial-card"
                type="button"
                onClick={() => runStarter(starter)}
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

        <section className="discover-section" aria-labelledby="discover-intention-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-intention-title">Shop with intention</h2>
              <p>Browse a category with its filter already set.</p>
            </div>
            <Link className="discover-section-link" href="/catalog">
              View all
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </header>
          <div className="discover-intention-rail">
            {intentionCategories.map((category) => (
              <Link
                className="discover-intention-tile"
                key={category.categoryKey}
                href={`/catalog?domain=${category.domain}&category_key=${category.categoryKey}`}
              >
                <span className="discover-intention-media">
                  <img
                    src={category.image}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    width={1200}
                    height={800}
                  />
                </span>
                <span className="discover-intention-label">{category.label}</span>
              </Link>
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
                Browse a considered edit, or describe what you need and let
                Mosaic retrieve the strongest matches.
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
          <LabsSignal />
          <div className="discover-labs-inner">
            <div className="discover-labs-copy">
              <p className="discover-labs-kicker">Mosaic Labs</p>
              <h2 id="discover-labs-title">
                Built for how you <em>think.</em>
              </h2>
              <p className="discover-labs-lede">
                See how Mosaic retrieves candidates, ranks results, and grounds recommendations.
              </p>
              <Link className="discover-labs-cta" href="/mosaic-labs">
                Explore Mosaic Labs
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            </div>
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
          </div>
        </section>
      </div>
    </div>
  );
}
