import {
  ArrowRight,
  Database,
  GitCompareArrows,
  Heart,
  Menu,
  Search,
  ShieldCheck,
  ShoppingBag,
  Truck,
  UserRound,
  X,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { Link } from "wouter";
import { MosaicMark } from "../components/MosaicMark";
import { missionLabHref, timedMosaicLabMissions } from "../labMissions";
import { useNavigate } from "../navigation";
import type { Domain } from "../types";

/**
 * The landing board is a two-column card: an uncropped photograph on the left
 * and a cream panel on the right holding the nav, headline, search, category
 * row, and service band. Copy is fixed to the board; every element still
 * routes, so the search field and the five tiles enter the live retrieval path.
 */
interface Category {
  slug: string;
  label: string;
  lines: [string, string];
  domain: Domain;
  query: string;
}

const categories: Category[] = [
  {
    slug: "audio",
    label: "Audio",
    lines: ["Focus in", "perfect sound"],
    domain: "consumer_electronics",
    query: "Over-ear headphones for focused work",
  },
  {
    slug: "workspace",
    label: "Workspace",
    lines: ["Comfort that", "moves with you"],
    domain: "home_office",
    query: "Ergonomic task seating for long sessions",
  },
  {
    slug: "performance",
    label: "Performance",
    lines: ["Engineered for", "every stride"],
    domain: "running_fitness",
    query: "Cushioned running shoes for daily training",
  },
  {
    slug: "lifestyle-tech",
    label: "Lifestyle Tech",
    lines: ["Tools that", "simplify life"],
    domain: "consumer_electronics",
    query: "Displays and everyday tech that simplify a desk",
  },
  {
    slug: "home",
    label: "Home",
    lines: ["Spaces that", "inspire calm"],
    domain: "home_office",
    query: "Calm home office pieces",
  },
];

const services = [
  {
    Icon: Search,
    title: "Lexical + fuzzy",
    lines: ["FTS and pg_trgm", "recover intent and typos"],
  },
  {
    Icon: Database,
    title: "Semantic retrieval",
    lines: ["pgvector on Aurora", "captures product intent"],
  },
  {
    Icon: GitCompareArrows,
    title: "Fuse + rerank",
    lines: ["RRF combines signals", "before final ordering"],
  },
  {
    Icon: ShieldCheck,
    title: "Cited answers",
    lines: ["Agent tools gather", "inspectable evidence"],
  },
];

export function DiscoverPage() {
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");

  function search(nextQuery: string, domain?: Domain) {
    const params = new URLSearchParams({ q: nextQuery });
    if (domain) params.set("domain", domain);
    navigate(`/search?${params}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length >= 2) search(trimmed);
  }

  return (
    <div className="landing-stage">
      <section className="discover-hero">
        <figure className="hero-image">
          <img
            src="/assets/images/mosaic/hero-landing-scene.webp"
            alt="Sunlit workspace with an ergonomic chair, headphones on a marble stand, and a running shoe"
            width={1586}
            height={992}
          />
        </figure>

        <div className="hero-panel">
          <header className="landing-nav">
            <Link className="landing-nav-brand" href="/" aria-label="Mosaic home">
              <MosaicMark />
              <strong>Mosaic</strong>
            </Link>
            <nav
              className={navOpen ? "landing-links open" : "landing-links"}
              aria-label="Storefront"
            >
              <Link className="active" href="/" onClick={() => setNavOpen(false)}>
                Discover
              </Link>
              <Link href="/catalog" onClick={() => setNavOpen(false)}>
                Shop
              </Link>
              <Link href="/search" onClick={() => setNavOpen(false)}>
                Collections
              </Link>
              <Link href="/mosaic-labs" onClick={() => setNavOpen(false)}>
                Mosaic Labs
              </Link>
            </nav>
            <div className="landing-actions">
              <button type="button" aria-label="Account">
                <UserRound size={19} strokeWidth={1.5} />
              </button>
              <button type="button" aria-label="Saved products">
                <Heart size={19} strokeWidth={1.5} />
              </button>
              <button type="button" aria-label="Bag">
                <ShoppingBag size={19} strokeWidth={1.5} />
              </button>
            </div>
            <button
              className="landing-nav-toggle"
              type="button"
              aria-label={navOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={navOpen}
              onClick={() => setNavOpen((current) => !current)}
            >
              {navOpen ? <X size={19} /> : <Menu size={19} />}
            </button>
          </header>

          <div className="hero-content">
            <h1 className="hero-display">
              Search,
              <br />
              re-engineered.
            </h1>
            <p className="hero-script">Mosaic</p>
            <p className="hero-sub">
              Agentic product discovery on Aurora PostgreSQL,
              <br />
              with filters, fusion, reranking, and sources.
            </p>

            <form className="hero-search" onSubmit={submit} role="search">
              <Search size={21} strokeWidth={1.6} aria-hidden="true" />
              <input
                aria-label="Search products"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search products, categories, or inspiration"
                minLength={2}
              />
              {/* Not disabled on an empty field: the board draws this button
                  solid maroon, and the global button:disabled rule renders it
                  at 50% opacity. Submitting an empty query is a no-op. */}
              <button type="submit">Search</button>
            </form>

            <h2 className="hero-section-label">Shop by category</h2>
            <div className="category-row">
              {categories.map(({ slug, label, lines, domain, query: tileQuery }) => (
                <button
                  className="category-card"
                  key={slug}
                  type="button"
                  onClick={() => search(tileQuery, domain)}
                >
                  <img
                    src={`/assets/images/mosaic/category/${slug}.webp`}
                    alt=""
                    width={125}
                    height={168}
                  />
                  <span>
                    <strong>{label}</strong>
                    <small>
                      {lines[0]}
                      <br />
                      {lines[1]}
                    </small>
                  </span>
                </button>
              ))}
            </div>

            <section className="service-band" aria-label="Shopping services">
              {services.map(({ Icon, title, lines }) => (
                <div key={title}>
                  <Icon size={29} strokeWidth={1.3} aria-hidden="true" />
                  <span>
                    <strong>{title}</strong>
                    <small>
                      {lines[0]}
                      <br />
                      {lines[1]}
                    </small>
                  </span>
                </div>
              ))}
            </section>
          </div>
        </div>
      </section>

      <section className="discover-missions" aria-labelledby="discover-missions-title">
        <div className="discover-missions-heading">
          <div>
            <p className="eyebrow">Mosaic Labs</p>
            <h2 id="discover-missions-title">Start with the golden set.</h2>
          </div>
          <p>
            {timedMosaicLabMissions.length} timed retrieval checks:{" "}
            {timedMosaicLabMissions.map((mission) => mission.title.toLowerCase()).join(", ")}.
          </p>
          <Link className="discover-missions-link" href="/mosaic-labs">
            View mission board <ArrowRight size={16} />
          </Link>
        </div>
        <ol className="discover-mission-grid">
          {timedMosaicLabMissions.map((mission, index) => (
            <li key={mission.id}>
              <Link href={missionLabHref(mission)}>
                <span className="discover-mission-number">0{index + 1}</span>
                <strong>{mission.title}</strong>
                <code>{mission.query}</code>
                <span className={`discover-mission-state ${mission.checkpoint}`}>
                  {mission.checkpoint === "repair" ? "Repair checkpoint" : "Golden query"}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
