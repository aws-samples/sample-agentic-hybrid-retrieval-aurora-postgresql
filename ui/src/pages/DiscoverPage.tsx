import { ArrowRight, Search, Sparkles } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "wouter";
import { CatalogSearchComposer } from "../components/CatalogSearchComposer";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { ProductCard } from "../components/ProductCard";
import { coreMosaicLabs, retrievalExampleHref } from "../labMissions";
import { productImageMap } from "../media";
import { RETRIEVAL_SURFACE, useNavigate } from "../navigation";
import { armLanguage } from "../retrievalLanguage";
import { showcaseCatalogPage } from "../showcase";
import type { SearchFilters } from "../types";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

type EditorialStory = {
  topic: string;
  title: string;
  caption: string;
  query: string;
  image: string;
  imageFit?: "cover";
  mode?: "search" | "ask";
  filters: Pick<SearchFilters, "domain" | "category_key">;
};

/**
 * Three editorial entries below the hero, each of which runs a real request.
 *
 * They used to be three same-shaped white cards in a row. Now the first is a
 * full-width image-led band and the other two sit beside it as photographs with
 * their copy on bare canvas, so the section reads as an edit rather than as three
 * containers.
 */
export const editorialStories: EditorialStory[] = [
  {
    topic: "Over-ear headphones",
    title: "For focus, and for the long way home",
    caption:
      "Comfort, isolation, and battery life weighed together, not one at a time.",
    query: "Find the best over-ear headphones for focus and travel.",
    image: "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    // The catalog plates are 3:2 and this frame is wider, so it fills rather
    // than sitting letterboxed inside it.
    imageFit: "cover",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
  {
    topic: "Workspace",
    title: "Made to be sat in all day",
    caption: "Fit, budget, and must-haves become real catalog constraints.",
    query:
      "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.",
    image: "/assets/images/mosaic/category/workspace.webp",
    filters: {
      domain: "home_office",
      category_key: "ergonomic-office-chairs",
    },
  },
  {
    topic: "Audio",
    title: "Ask, and compare the facts",
    caption: "Mosaic answers from catalog records and shows the ones it used.",
    query: "Comfortable over-ear headphones for a 14-hour flight",
    image: "/assets/images/mosaic/category/audio.webp",
    mode: "ask",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
];

/**
 * The five curated hero prompts, each with the category it browses.
 *
 * Each chip searches for exactly the words printed on it. The constraint beside
 * those words is what puts a premium, photographed cohort behind them, and Shop
 * renders it as a removable filter chip, so nothing is hidden.
 *
 * These shipped unconstrained for one revision, on the argument that plain language
 * ought to be enough. Measured against the live 500,000-row catalog, that argument
 * produced this:
 *
 *   "Focus headphones"           1 of 12 distinct photographs
 *   "Quiet home office"          1 of 12
 *   "Travel-ready audio"         2 of 12
 *   "Recovery essentials"        2 of 12
 *   "A chair for long workdays"  8 of 12
 *
 * The corpus is why. "Focus headphones" collides with three synthetic brands named
 * FocusErgonomics, FocusOffice and FocusSystems, so the lexical arm answers with
 * `acoustic-headphones` — a subcategory that has no commissioned photography at all,
 * which sends all twelve rows to one domain-neutral plate. "Quiet home office" lands
 * in `mesh-office-chairs` the same way. Constrained to a category that owns a deep
 * pool, the same five labels measure 12, 12, 11, 12 and 12 of 12.
 *
 * Nothing here is misspelled — the imperfect query the workshop needs is one a
 * shopper types into this field themselves.
 */
export const heroPrompts: Array<{
  label: string;
  filters: Required<Pick<SearchFilters, "domain" | "category_key">>;
}> = [
  {
    label: "Focus headphones",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
  {
    label: "A chair for long workdays",
    filters: { domain: "home_office", category_key: "ergonomic-office-chairs" },
  },
  {
    label: "Travel-ready audio",
    filters: {
      domain: "consumer_electronics",
      category_key: "true-wireless-earbuds",
    },
  },
  {
    label: "Quiet home office",
    filters: { domain: "home_office", category_key: "quiet-keyboards" },
  },
  {
    label: "Recovery essentials",
    filters: { domain: "running_fitness", category_key: "mobility-tools" },
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
export const intentionCategories = [
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

/**
 * The Playground band's three cards, which are also the three required labs.
 *
 * This used to be two grids: three stage cards that all linked to the Playground
 * root, and below them three scenario cards that linked to the real scenarios and
 * printed each scenario's query verbatim. Six cards for three destinations, and
 * the queries included Lab 1's deliberately misspelled one — Mosaic's own copy
 * spelling "wirless" and "hedphones" on the landing page.
 *
 * One card per lab now, deep-linked to its scenario. The misspelled query belongs
 * to the shopper who types it, so it appears in an input the participant owns and
 * nowhere in Mosaic's voice.
 */
const labStages = [
  {
    number: "01",
    label: "Retrieve",
    // Not the mission's own `discover_label`: those are written for the Playground
    // and two of the three name the mechanism — "Candidate recall across
    // retrievers" and "RRF ranking before rerank". Printing them here would put
    // "RRF" on the landing page.
    title: "Three ways to find one product",
    caption: "Exact terms, close spelling, and meaning, over one Aurora catalog.",
    graphic: "retrieve" as const,
  },
  {
    number: "02",
    label: "Rank",
    title: "Watch the order change",
    caption: "Candidates move as results are combined and then reranked.",
    graphic: "rank" as const,
  },
  {
    number: "03",
    label: "Reason",
    title: "An answer that cites its sources",
    caption: "Every claim traced back to the product record it came from.",
    graphic: "reason" as const,
  },
];

/**
 * The three scenes behind the Playground cards.
 *
 * Photography-led rather than diagrammatic, and labelled in the shopping
 * vocabulary: the strip under the first scene used to read "FTS / pg_trgm /
 * pgvector" and the second "RRF -> model rerank", which put three Postgres
 * feature names and an academic acronym on the landing page. The mechanism names
 * belong on the Playground, next to the numbers that come out of them.
 *
 * The evidence card quotes the Auraluxe H9's real catalog record: adaptive noise
 * cancellation and `battery_hours: 60`, both from data/curated/demo_products.json.
 */
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
          {armLanguage.map((arm) => <span key={arm.key}>{arm.label}</span>)}
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
          <span>Before reranking</span>
          <ArrowRight size={14} />
          <strong>Final position</strong>
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
        <small>From the product record</small>
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

// Discover is an editorial entry surface, not a live-search result. Loading
// these fixed premium-cohort cards locally prevents the Shop band from
// appearing a second after the rest of the page, while Shop remains the
// authoritative live catalog and retrieval surface.
const featuredPreview = showcaseCatalogPage({}, 0, 4, "featured").products;

export function DiscoverPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const previewImages = useMemo(() => productImageMap(featuredPreview), []);
  const reduceMotion = useReducedMotion() ?? false;
  const labCards = useMemo(
    () =>
      labStages
        .map((stage) => ({
          ...stage,
          mission: coreMosaicLabs.find(
            (mission) => mission.stage === stage.graphic,
          ),
        }))
        .filter((card) => card.mission),
    [],
  );

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

  function runStory(story: EditorialStory) {
    if (story.mode === "ask") {
      askMosaic(story.query, story.filters);
      return;
    }
    search(story.query, story.filters);
  }

  const [featuredStory, ...secondaryStories] = editorialStories;

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
          <h1>
            <span>Objects that shape</span>
            <em>your world.</em>
          </h1>
          <p className="discover-hero-sub">
            Search naturally. Mosaic understands the words, meaning, and details
            that matter.
          </p>
          <div className="discover-search" role="search">
            {/* No rotating ghost query. The headline says "Search naturally" and
                the field then cycled through "Sonora WH-C720" and "Mosaic Auraluxe
                H9" — exact model numbers, which read as a demo fixture rather than
                as an invitation. A plain placeholder asks for the thing the hero
                just promised. */}
            <CatalogSearchComposer
              inputLabel="Search products"
              leadingIcon={<GenerativeSearchIcon size={20} />}
              onSubmit={search}
              onValueChange={setQuery}
              placeholder="Describe what you're looking for..."
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
          </div>
          {/* Each chip searches for exactly the words on it, inside the category
              it names. */}
          <div className="discover-hero-prompts">
            <span>Try a search</span>
            {heroPrompts.map((prompt) => (
              <button
                key={prompt.label}
                type="button"
                onClick={() => search(prompt.label, prompt.filters)}
              >
                {prompt.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="discover-body">
        <section className="discover-section" aria-labelledby="discover-starters-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-starters-title">
                Made for the way you work, move, and unwind.
              </h2>
            </div>
          </header>
          <div className="discover-editorial-grid">
            <button
              className="discover-editorial-card is-featured"
              type="button"
              onClick={() => runStory(featuredStory)}
              aria-label={featuredStory.query}
            >
              <span
                className={
                  featuredStory.imageFit === "cover"
                    ? "discover-editorial-media is-cover"
                    : "discover-editorial-media"
                }
              >
                <img
                  src={featuredStory.image}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
              </span>
              <span className="discover-editorial-body">
                <small>{featuredStory.topic}</small>
                <strong>{featuredStory.title}</strong>
                <em>{featuredStory.caption}</em>
                <span className="discover-editorial-run">
                  Explore the edit
                  <ArrowRight size={14} aria-hidden="true" />
                </span>
              </span>
            </button>
            {secondaryStories.map((story) => (
              <button
                key={story.topic}
                className="discover-editorial-card"
                type="button"
                onClick={() => runStory(story)}
                aria-label={story.query}
              >
                <span
                  className={
                    story.imageFit === "cover"
                      ? "discover-editorial-media is-cover"
                      : "discover-editorial-media"
                  }
                >
                  <img src={story.image} alt="" loading="lazy" decoding="async" />
                </span>
                <span className="discover-editorial-body">
                  <small>{story.topic}</small>
                  <strong>{story.title}</strong>
                  <em>{story.caption}</em>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="discover-section" aria-labelledby="discover-shop-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-shop-title">Shop with intention</h2>
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
                Mosaic find the strongest matches.
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
          {/* The category tiles were their own section with its own "Shop with
              intention" heading directly above this one, so the landing asked
              twice for the same errand. Folded in under one heading: the edit
              first, then the categories as the other way into Shop. */}
          <div className="discover-intention-fold">
            <p>Browse a category with its filter already set.</p>
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
          </div>
        </section>

        <section className="discover-section discover-labs" aria-labelledby="discover-labs-title">
          {/* No decorative light figure. Blurred to 7px it read as a lens flare in
              the bottom-left corner, not as three arms converging, and the three
              scenes beside it make the same point with photographs. */}
          <div className="discover-labs-inner">
            <div className="discover-labs-copy">
              <h2 id="discover-labs-title">
                Built for how you <em>think.</em>
              </h2>
              <p className="discover-labs-lede">
                See how Mosaic finds candidates, ranks them, and grounds every
                recommendation it makes.
              </p>
              <Link className="discover-labs-cta" href={RETRIEVAL_SURFACE.path}>
                Open the {RETRIEVAL_SURFACE.label}
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            </div>
            <div className="discover-labs-grid">
              {labCards.map((lab) => (
                <Link
                  className="discover-lab-card"
                  key={lab.label}
                  href={retrievalExampleHref(lab.mission!)}
                  aria-label={`${lab.label}: ${lab.title}`}
                >
                  <span className="discover-lab-graphic">
                    <LabGraphic variant={lab.graphic} />
                  </span>
                  <span className="discover-lab-copy">
                    <small>
                      {lab.number} · {lab.label}
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
