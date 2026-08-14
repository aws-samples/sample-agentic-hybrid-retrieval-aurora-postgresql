import { Menu, Search, ShoppingBag, X } from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "wouter";
import { useCommerce } from "../commerce";
import { MosaicMark } from "./MosaicMark";

/**
 * The one storefront header.
 *
 * Discover used to draw its own copy of this, and the two drifted: the landing
 * showed a serif title-case wordmark at 74px tall, every other surface showed an
 * uppercase sans wordmark at 72px. The reference boards carry one header across
 * all three panels, so there is one component and one rule block.
 */
const navLinks = [
  { to: "/", label: "Discover" },
  { to: "/catalog", label: "Shop" },
  { to: "/mosaic-labs", label: "Mosaic Labs" },
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
  return pathname.startsWith(to);
}

export function SiteHeader({ inert = false }: { inert?: boolean }) {
  const [open, setOpen] = useState(false);
  const { itemCount, openCart } = useCommerce();
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const close = () => setOpen(false);

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
        className={open ? "site-nav open" : "site-nav"}
        aria-label="Storefront"
      >
        {navLinks.map(({ to, label }) => (
          <Link
            key={to}
            href={to}
            className={isActive(pathname, to) ? "active" : ""}
            onClick={close}
          >
            {label}
          </Link>
        ))}
      </nav>

      <div className="site-actions">
        <Link className="site-icon" href="/catalog" aria-label="Search products">
          <Search size={17} />
        </Link>
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
          onClick={() => setOpen((current) => !current)}
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>
    </header>
  );
}
