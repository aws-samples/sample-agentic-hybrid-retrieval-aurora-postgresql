import { Menu, ShoppingBag, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation } from "wouter";
import { useCommerce } from "../commerce";
import {
  RETRIEVAL_SURFACE,
  forwardedSearchFilters,
  playgroundQueryHref,
  useSearchParams,
} from "../navigation";
import { MosaicMark } from "./MosaicMark";

/**
 * The one storefront header.
 *
 * Discover used to draw its own copy of this, and the two drifted: the landing
 * showed a serif title-case wordmark at 74px tall, every other surface showed an
 * uppercase sans wordmark at 72px. The reference boards carry one header across
 * all three panels, so there is one component and one rule block.
 */
/**
 * Discover, Shop, Playground. Desire, decide, understand.
 *
 * Three entries and nothing else: the third used to print "Observatory" with an
 * "Optional" badge clipped to it, which spent the only spare line in the header
 * telling participants the surface did not matter.
 */
const navLinks = [
  { to: "/", label: "Discover" },
  { to: "/catalog", label: "Shop" },
  { to: RETRIEVAL_SURFACE.path, label: RETRIEVAL_SURFACE.label },
];

function isActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/" || pathname === "/discover";
  if (to === "/catalog") {
    return (
      pathname.startsWith("/catalog")
      || pathname.startsWith("/search")
      || pathname.startsWith("/products/")
    );
  }
  // The Playground's other two lenses still live under their own paths, and the
  // nav entry has to stay lit on them or the header would report the participant
  // is nowhere.
  if (to === RETRIEVAL_SURFACE.path) {
    return pathname.startsWith(to) || pathname.startsWith("/mosaic-labs");
  }
  return pathname.startsWith(to);
}

export function SiteHeader({ inert = false }: { inert?: boolean }) {
  const [open, setOpen] = useState(false);
  const { itemCount, openCart } = useCommerce();
  const [location] = useLocation();
  const [searchParams] = useSearchParams();
  const pathname = location.split("?")[0];
  const close = () => setOpen(false);
  /**
   * The Playground entry carries the shopper's current Shop request with it.
   *
   * The only other way to hand a query over is a link inside Shop's collapsed
   * "Why these results" disclosure, so a participant who searched and then reached
   * for the header arrived at a Playground about a different query — three separate
   * demonstrations rather than one request travelling through the product. Nothing
   * is carried when Shop has no active search, and the Playground says out loud when
   * something was.
   */
  const playgroundHref = useMemo(() => {
    // wouter's useLocation returns the path without the query string, so the search
    // has to come from its own hook.
    if (!pathname.startsWith("/catalog")) return RETRIEVAL_SURFACE.path;
    const query = searchParams.get("q")?.trim();
    if (!query) return RETRIEVAL_SURFACE.path;
    return playgroundQueryHref(query, forwardedSearchFilters(searchParams));
  }, [pathname, searchParams]);

  return (
    <header
      className="site-header"
      inert={inert || undefined}
      aria-hidden={inert || undefined}
    >
      <Link className="site-brand" href="/" onClick={close} aria-label="Mosaic home">
        <MosaicMark />
        <strong>Mosaic</strong>
      </Link>

      <nav
        id="storefront-navigation"
        className={open ? "site-nav open" : "site-nav"}
        aria-label="Storefront"
      >
        {navLinks.map(({ to, label }) => (
          <Link
            key={to}
            href={to === RETRIEVAL_SURFACE.path ? playgroundHref : to}
            className={isActive(pathname, to) ? "active" : ""}
            aria-current={isActive(pathname, to) ? "page" : undefined}
            onClick={close}
          >
            <span>{label}</span>
          </Link>
        ))}
      </nav>

      <div className="site-actions">
        <button
          className="site-icon site-bag"
          type="button"
          aria-label={`Bag, ${itemCount} ${itemCount === 1 ? "item" : "items"}`}
          data-cart-target
          onClick={openCart}
        >
          <ShoppingBag size={17} />
          {itemCount ? (
            <span className="bag-count">{itemCount > 99 ? "99+" : itemCount}</span>
          ) : null}
        </button>
        <button
          className="site-icon site-menu"
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="storefront-navigation"
          onClick={() => setOpen((current) => !current)}
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>
    </header>
  );
}
