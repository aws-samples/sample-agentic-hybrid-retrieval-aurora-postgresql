import {
  ArrowRight,
  GitCompareArrows,
  Menu,
  ScanSearch,
  Search,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  X,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { Link } from "wouter";
import { useCommerce } from "../commerce";
import { MosaicMark } from "../components/MosaicMark";
import { useNavigate } from "../navigation";

const starterQueries = [
  {
    label: "Shared office",
    query: "Quiet wireless keyboard for a shared office under $180",
  },
  {
    label: "Marathon training",
    query: "Marathon shoe with cushioning under $180",
  },
  {
    label: "Long-haul travel",
    query: "Headphones for a 14-hour flight with strong noise cancellation",
  },
  {
    label: "All-day comfort",
    query: "Ergonomic chair for a 12-hour workday with adjustable lumbar support",
  },
];

const workshopStages = [
  {
    number: "01",
    label: "Retrieve",
    detail: "Build the candidate universe",
    Icon: ScanSearch,
  },
  {
    number: "02",
    label: "Rank",
    detail: "Fuse, rerank, and explain",
    Icon: GitCompareArrows,
  },
  {
    number: "03",
    label: "Reason",
    detail: "Orchestrate cited evidence",
    Icon: ShieldCheck,
  },
];

export function DiscoverPage() {
  const navigate = useNavigate();
  const { itemCount, openCart } = useCommerce();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");

  function search(nextQuery: string) {
    const params = new URLSearchParams({ q: nextQuery });
    navigate(`/catalog?${params}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length >= 2) search(trimmed);
  }

  return (
    <div className="discover-experience">
      <img
        className="discover-backdrop"
        src="/assets/images/mosaic/hero-landing-scene.webp"
        alt="A refined workspace with an ergonomic chair, display, headphones, and natural light"
        width={1568}
        height={1908}
      />
      <div className="discover-scrim" aria-hidden="true" />

      <header className="discover-nav">
        <Link className="discover-brand" href="/" aria-label="Mosaic home">
          <MosaicMark />
          <strong>Mosaic</strong>
        </Link>
        <nav className={navOpen ? "discover-links open" : "discover-links"} aria-label="Storefront">
          <Link className="active" href="/" onClick={() => setNavOpen(false)}>Discover</Link>
          <Link href="/catalog" onClick={() => setNavOpen(false)}>Shop</Link>
          <Link href="/mosaic-labs" onClick={() => setNavOpen(false)}>Mosaic Labs</Link>
        </nav>
        <button
          className="discover-bag"
          type="button"
          aria-label={`Bag, ${itemCount} ${itemCount === 1 ? "item" : "items"}`}
          onClick={openCart}
        >
          <ShoppingBag size={19} />
          {itemCount ? <span className="bag-count">{itemCount > 99 ? "99+" : itemCount}</span> : null}
        </button>
        <button
          className="discover-nav-toggle"
          type="button"
          aria-label={navOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((current) => !current)}
        >
          {navOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      <main className="discover-content">
        <div className="discover-kicker">
          <Sparkles size={15} />
          Agentic product discovery on Aurora PostgreSQL
        </div>
        <h1>Discover what you actually mean.</h1>
        <p>
          Search naturally. Keep hard constraints authoritative. Compare the
          strongest options with evidence you can inspect.
        </p>

        <form className="discover-search" onSubmit={submit} role="search">
          <Search size={22} aria-hidden="true" />
          <input
            aria-label="Search products"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="What are you looking for?"
            minLength={2}
          />
          <button type="submit" aria-label="Search Mosaic">
            <span>Explore</span>
            <ArrowRight size={18} />
          </button>
        </form>

        <div className="discover-presets" aria-label="Suggested searches">
          <span>Try</span>
          {starterQueries.map((preset) => (
            <button key={preset.label} type="button" onClick={() => search(preset.query)}>
              <strong>{preset.label}</strong>
              <small>{preset.query}</small>
              <ArrowRight size={15} />
            </button>
          ))}
        </div>
      </main>

      <Link className="discover-workshop-rail" href="/mosaic-labs">
        <span className="discover-workshop-label">
          <small>DAT410</small>
          Build the system
        </span>
        <ol>
          {workshopStages.map(({ number, label, detail, Icon }) => (
            <li key={label}>
              <Icon size={18} />
              <span>
                <small>{number}</small>
                <strong>{label}</strong>
                <em>{detail}</em>
              </span>
            </li>
          ))}
        </ol>
        <ArrowRight size={19} />
      </Link>
    </div>
  );
}
