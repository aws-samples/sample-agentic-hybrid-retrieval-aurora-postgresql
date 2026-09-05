import { ArrowRight, Search, Send, Star } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { CatalogSearchComposer } from "../components/CatalogSearchComposer";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { ProductCard } from "../components/ProductCard";
import { formatPrice } from "../format";
import {
  coreMosaicLabs,
  retrievalExampleHref,
  type MosaicLabMission,
} from "../labMissions";
import { productImageMap } from "../media";
import {
  RETRIEVAL_SURFACE,
  playgroundQueryHref,
  useNavigate,
} from "../navigation";
import { armLanguage } from "../retrievalLanguage";
import { showcaseCatalogPage } from "../showcase";
import type {
  CatalogSummary,
  ProductSummary,
  ReviewHighlight,
  SearchFilters,
} from "../types";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

type EditorialStory = {
  topic: string;
  title: string;
  caption: string;
  query: string;
  image: string;
  imageFit?: "cover";
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
    topic: "Running & fitness",
    title: "For the miles after the miles",
    caption: "Portable recovery tools for tired legs and limited carry-on space.",
    query: "Recovery tools for sore calves after long runs that fit in a carry-on.",
    image: "/assets/images/mosaic/category/performance.webp",
    imageFit: "cover",
    filters: {
      domain: "running_fitness",
      category_key: "mobility-tools",
    },
  },
];

/**
 * A lab's own request, addressed to Shop rather than to the Playground.
 *
 * The gates are encoded by `playgroundQueryHref` and the result is only
 * re-pointed at `/catalog`, so exactly one place in the UI decides which filters
 * may travel on a URL and how they are spelled. A second encoder written here
 * would drift from `forwardedSearchFilters`, and Shop would then retrieve a
 * wider pool than the lab asked for while still reporting the lab's own gates.
 *
 * `mission` is what makes the arrival a lab rather than a search: Shop reads it
 * to decide whether the Lab 1 callout applies, and to grade a reasoning lab's
 * answer against its own checkpoint.
 *
 * The reasoning lab also carries `ask=1`, because its request is a question for
 * the agent rather than a query for the product grid. Shop opens Ask Mosaic on
 * `ask` and `mode` only, so without it the chip would land Lab 3 on a page of
 * ranked products and the lab it names would be nowhere on screen.
 */
function shopMissionHref(mission: MosaicLabMission): string {
  const encoded = playgroundQueryHref(
    mission.query,
    mission.filters as Record<string, unknown>,
  );
  const params = new URLSearchParams(encoded.slice(encoded.indexOf("?") + 1));
  params.set("view", "results");
  params.set("mission", mission.id);
  if (mission.stage === "reason") params.set("ask", "1");
  return `/catalog?${params}`;
}

/**
 * The hero's three chips are the three labs' own queries, in lab order.
 *
 * They used to be five curated phrases, each constrained to a photogenic
 * category. That made a handsome landing and it hid the workshop: a participant
 * arrived, searched something that worked, and never met the broken system they
 * were there to repair. The session is Broken -> Diagnose -> Fix -> Prove, and
 * the break has to be reachable from the first screen.
 *
 * So the first chip prints `noice cancelng hedfones`, misspelled, because that
 * is Lab 1's canonical query and running it is how a participant reproduces the
 * fault. The label is the query, verbatim, exactly as before: a chip that ran
 * something other than its own words would make Shop's retrieval receipt a
 * receipt for a request nobody made.
 *
 * Links rather than buttons. These are addresses a participant can copy, reopen,
 * and compare, which a click handler is not.
 */
export const heroPrompts: Array<{ label: string; href: string }> =
  coreMosaicLabs.map((mission) => ({
    label: mission.query,
    href: shopMissionHref(mission),
  }));

/**
 * Merchandising doors under the hero, each a plain link into Shop with its
 * filter already set.
 *
 * The count on a chip is the `total` from the same /api/catalog/products
 * request Shop runs when the door opens, taken with `limit: 1` so only the
 * number travels. Nothing is hardcoded: a door whose count has not arrived,
 * failed, or came back zero simply does not render, because a chip promising
 * an empty shelf is worse than no chip.
 */
export const merchandisingDoors: Array<{
  label: string;
  filters: SearchFilters;
  params: Record<string, string>;
}> = [
  {
    label: "Under $200",
    filters: { max_price_cents: 20000 },
    params: { max_price_cents: "20000" },
  },
  {
    label: "In stock now",
    filters: { in_stock_only: true },
    params: { in_stock_only: "true" },
  },
  {
    label: "Rated 4★ and up",
    filters: { min_rating: 4 },
    params: { min_rating: "4" },
  },
];

/**
 * Browse entries for the category rail.
 *
 * Every tile is a real `category_key` the catalog filters on, illustrated by
 * that category's own commissioned plate rather than by a product photograph
 * borrowed from a neighbouring category. Deliberately no product counts on
 * the tiles: the merchandising chips at the top of the page already carry the
 * live numbers, and six more here would turn a visual browse path into a
 * table.
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
 * The evidence card must illustrate the scenario the card links to. It quoted the
 * Auraluxe H9's headphone record while Lab 3's `agentic-research` mission is a
 * compound ergonomic-chair-and-quiet-keyboard request, so a participant met
 * headphones here and a chair and keyboard one click later. It now quotes
 * product 370001, Mosaic Forma Ergonomic Office Chair -- that mission's
 * highest-graded component in `data/evals/canonical_queries.jsonl` -- citing its
 * real `recommended_hours: 12` and `lumbar_support: "Dynamic"` from
 * data/curated/demo_products.json.
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
        src="/assets/images/mosaic/ho-ergonomic-office-chairs-forma-ergonomic-catalog-3x2.webp"
        alt=""
        loading="lazy"
        decoding="async"
      />
      <span className="discover-lab-evidence">
        <small>From the product record</small>
        <strong>Forma Ergonomic</strong>
        <span>
          Rated for twelve hour days <b>[1]</b>
        </span>
        <span>
          Dynamic lumbar support <b>[2]</b>
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

/**
 * One verbatim review excerpt at a time, cycling below the merchandising row.
 *
 * Every quote is the opening sentence of a real evidence row, and each cycles
 * to the next after a reading pause. The cycle pauses under a pointer or
 * keyboard focus, and under reduced motion it never advances on its own — the
 * dots remain the way through. Nothing here renders until the highlights
 * arrive: a quotation placeholder would be an invented customer.
 */
function DiscoverVoices({
  voices,
  reduceMotion,
}: {
  voices: ReviewHighlight[];
  reduceMotion: boolean;
}) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (reduceMotion || paused || voices.length < 2) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % voices.length);
    }, 6500);
    return () => window.clearInterval(timer);
  }, [reduceMotion, paused, voices.length]);

  const voice = voices[index];
  return (
    <section
      className="discover-voices"
      aria-label="What others are saying"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="discover-voices-lede">What others are saying</span>
      {/* Remounting on review_id is what replays the entrance animation. */}
      <figure className="discover-voice" key={voice.review_id}>
        <blockquote>&ldquo;{voice.quote}&rdquo;</blockquote>
        <figcaption>
          <span className="discover-voice-rating">
            <Star size={13} aria-hidden="true" />
            {voice.rating.toFixed(1)}
          </span>
          <Link href={`/products/${voice.product_id}`}>
            {voice.product_title}
          </Link>
          {voice.verified_purchase ? <em>Verified purchase</em> : null}
        </figcaption>
      </figure>
      {voices.length > 1 ? (
        <span className="discover-voices-dots">
          {voices.map((entry, position) => (
            <button
              key={entry.review_id}
              type="button"
              className={position === index ? "is-active" : undefined}
              aria-label={`Review ${position + 1} of ${voices.length}`}
              aria-pressed={position === index}
              onClick={() => setIndex(position)}
            />
          ))}
        </span>
      ) : null}
    </section>
  );
}

export function DiscoverPage() {
  const navigate = useNavigate();
  // One photograph per card. Assigned across the whole set rather than per
  // product, because a per-product hash cannot guarantee distinctness.
  const previewImages = useMemo(() => productImageMap(featuredPreview), []);
  const reduceMotion = useReducedMotion() ?? false;
  const [doorCounts, setDoorCounts] = useState<ReadonlyMap<string, number>>(
    new Map(),
  );
  const [proof, setProof] = useState<CatalogSummary["total"] | null>(null);
  const [voices, setVoices] = useState<ReviewHighlight[]>([]);
  const [storyPicks, setStoryPicks] = useState<
    ReadonlyMap<string, ProductSummary[]>
  >(new Map());

  useEffect(() => {
    let active = true;
    // A door that fails stays hidden rather than showing a stale or invented
    // number, so rejections end here deliberately.
    for (const door of merchandisingDoors) {
      api.catalog(door.filters, 0, 1).then(
        (page) => {
          if (!active) return;
          setDoorCounts((counts) => new Map(counts).set(door.label, page.total));
        },
        () => {},
      );
    }
    // Each editorial story lists the top-rated picks from its own category, so
    // the copy column carries real rows rather than empty canvas. A story whose
    // read fails shows no rows, same as the doors.
    for (const story of editorialStories) {
      api.catalog(story.filters, 0, 3, "rating").then(
        (page) => {
          if (!active) return;
          setStoryPicks((picks) => new Map(picks).set(story.topic, page.products));
        },
        () => {},
      );
    }
    api.summary().then(
      (summary) => {
        if (active) setProof(summary.total);
      },
      () => {},
    );
    api.reviewHighlights().then(
      (highlights) => {
        if (active) setVoices(highlights);
      },
      () => {},
    );
    return () => {
      active = false;
    };
  }, []);

  const openDoors = merchandisingDoors.filter(
    (door) => (doorCounts.get(door.label) ?? 0) > 0,
  );
  const proofLine =
    proof && proof.reviews > 0 && proof.average_rating !== null ? proof : null;
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
    const params = new URLSearchParams({ q: nextQuery, view: "results" });
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.category_key) params.set("category_key", filters.category_key);
    navigate(`/catalog?${params}`);
  }

  function runStory(story: EditorialStory) {
    search(story.query, story.filters);
  }

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
          <h1 className="commerce-display">
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
              placeholder="Describe what you're looking for..."
              showSuggestions={false}
              suggestionsOnType={false}
              submitIcon={<Send size={16} aria-hidden="true" />}
              submitIconOnly
            />
          </div>
          {/* Each chip searches for exactly the words on it, under the gates its
              lab runs. `title` carries the full text for the reasoning lab's long
              question, which the chip truncates rather than wraps. */}
          <div className="discover-hero-prompts">
            <span>Try a search</span>
            {heroPrompts.map((prompt) => (
              <Link key={prompt.href} href={prompt.href} title={prompt.label}>
                {prompt.label}
              </Link>
            ))}
          </div>
        </div>
      </section>

      <div className="discover-body">
        {openDoors.length || proofLine ? (
          <section className="discover-merch" aria-label="Shop by what matters">
            {openDoors.length ? (
              <div className="discover-merch-doors">
                <span className="discover-merch-lede">Shop by what matters</span>
                {openDoors.map((door) => (
                  <Link
                    className="discover-merch-door"
                    key={door.label}
                    href={`/catalog?${new URLSearchParams(door.params)}`}
                  >
                    {door.label}
                    <span className="discover-merch-count">
                      {(doorCounts.get(door.label) ?? 0).toLocaleString()}
                    </span>
                  </Link>
                ))}
              </div>
            ) : null}
            {proofLine ? (
              <p className="discover-merch-proof">
                <Star size={14} aria-hidden="true" />
                <strong>{proofLine.average_rating?.toFixed(1)}</strong>
                average across {proofLine.reviews.toLocaleString()} customer
                reviews
              </p>
            ) : null}
          </section>
        ) : null}

        {voices.length ? (
          <DiscoverVoices voices={voices} reduceMotion={reduceMotion} />
        ) : null}

        <section className="discover-section" aria-labelledby="discover-starters-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-starters-title">
                Made for the way you work, move, and unwind.
              </h2>
              <p>A considered edit for focus, long workdays, and recovery.</p>
            </div>
          </header>
          <div className="discover-editorial-grid">
            {/* The photograph runs the story's query; the picks link straight to
                product pages; the button runs the same query under a label that
                names the errand. The card itself stopped being one big button
                the moment it carried links of its own. */}
            {editorialStories.map((story, index) => {
              const picks = storyPicks.get(story.topic) ?? [];
              return (
                <article
                  key={story.topic}
                  className={
                    index === 0
                      ? "discover-editorial-card is-featured"
                      : "discover-editorial-card"
                  }
                >
                  <button
                    type="button"
                    className={
                      story.imageFit === "cover"
                        ? "discover-editorial-media is-cover"
                        : "discover-editorial-media"
                    }
                    onClick={() => runStory(story)}
                    aria-label={story.query}
                  >
                    <img src={story.image} alt="" loading="lazy" decoding="async" />
                  </button>
                  <span className="discover-editorial-body">
                    <small>{story.topic}</small>
                    <strong>{story.title}</strong>
                    <em>{story.caption}</em>
                    {picks.length ? (
                      <span className="discover-editorial-picks">
                        {picks.map((product) => (
                          <Link
                            key={product.product_id}
                            href={`/products/${product.product_id}`}
                          >
                            <span className="discover-editorial-pick-title">
                              {product.title}
                            </span>
                            <span className="discover-editorial-pick-price">
                              {formatPrice(product.price_cents, product.currency)}
                            </span>
                          </Link>
                        ))}
                      </span>
                    ) : null}
                    <button
                      type="button"
                      className="discover-cta"
                      onClick={() => runStory(story)}
                    >
                      Shop {story.topic.toLowerCase()}
                    </button>
                  </span>
                </article>
              );
            })}
          </div>
        </section>

        <section className="discover-section" aria-labelledby="discover-shop-title">
          <header className="discover-section-heading">
            <div>
              <h2 id="discover-shop-title">Shop with intention</h2>
              <p>Thoughtfully designed. Expertly made.</p>
            </div>
            <Link className="discover-cta" href="/catalog">
              Shop all
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
              <Link className="discover-cta" href="/catalog?domain=running_fitness">
                Shop running &amp; fitness
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
                  <span className="discover-intention-label">
                    {category.label}
                  </span>
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
              <Link
                className="discover-cta discover-labs-cta"
                href={RETRIEVAL_SURFACE.path}
              >
                Open the {RETRIEVAL_SURFACE.label}
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
