import { CircleUserRound, Menu, ShoppingBag, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "wouter";
import { useCommerce } from "../commerce";
import { RETRIEVAL_SURFACE } from "../navigation";
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
  { to: RETRIEVAL_SURFACE.path, label: RETRIEVAL_SURFACE.label, optional: true },
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
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement | null>(null);
  const { itemCount, openCart } = useCommerce();
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const close = () => setOpen(false);

  useEffect(() => {
    if (!accountOpen) return;
    const dismiss = (event: MouseEvent) => {
      if (event.target instanceof Node && accountRef.current?.contains(event.target)) return;
      setAccountOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountOpen(false);
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [accountOpen]);

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
        {navLinks.map(({ to, label, optional }) => (
          <Link
            key={to}
            href={to}
            className={isActive(pathname, to) ? "active" : ""}
            aria-current={isActive(pathname, to) ? "page" : undefined}
            onClick={close}
          >
            <span>{label}</span>
            {optional ? <small className="site-nav-optional">Optional</small> : null}
          </Link>
        ))}
      </nav>

      <div className="site-actions">
        <div className="site-account" ref={accountRef}>
          <button
            className="site-icon"
            type="button"
            aria-label="Account"
            aria-expanded={accountOpen}
            onClick={() => setAccountOpen((current) => !current)}
          >
            <CircleUserRound size={17} />
          </button>
          {accountOpen ? (
            <div className="site-account-pop" role="status">
              <strong>Workshop guest</strong>
              <span>Sign-in is not part of this preview build.</span>
            </div>
          ) : null}
        </div>
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
