import { Menu, Search, ShoppingBag, UserRound, X } from "lucide-react";
import { ReactNode, useState } from "react";
import { Link, useLocation } from "wouter";
import { MosaicMark } from "./MosaicMark";

/**
 * Storefront chrome. The reference boards read as a catalog first and an
 * instrument second, so shopper navigation sits in the header and the workshop
 * surfaces stay in a visually separate group after a divider.
 */
const shopLinks = [
  { to: "/", label: "Discover" },
  { to: "/catalog", label: "Shop" },
  { to: "/search", label: "Collections" },
  { to: "/#catalog-overview", label: "Inspiration" },
];

function isActive(pathname: string, to: string) {
  return to === "/"
    ? pathname === "/" || pathname === "/discover"
    : pathname.startsWith(to);
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const isLanding = pathname === "/" || pathname === "/discover";
  const close = () => setOpen(false);

  return (
    <div className={isLanding ? "app-shell landing-shell" : "app-shell"}>
      {!isLanding && <header className="topbar">
        <Link className="brand" href="/" onClick={close} aria-label="Mosaic home">
          <MosaicMark />
          <strong>Mosaic</strong>
        </Link>

        <button
          className="icon-button mobile-menu"
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>

        <nav className={open ? "primary-nav open" : "primary-nav"}>
          {shopLinks.map(({ to, label }) => (
            <Link
              key={to}
              href={to}
              className={isActive(pathname, to) ? "active" : ""}
              onClick={close}
            >
              <span>{label}</span>
            </Link>
          ))}
        </nav>

        <div className="topbar-actions">
          <Link className="header-action" href="/search" aria-label="Search products">
            <Search size={18} />
          </Link>
          <button className="header-action" type="button" aria-label="Account">
            <UserRound size={18} />
          </button>
          <button className="bag-button" type="button" aria-label="Bag">
            <ShoppingBag size={19} />
          </button>
        </div>
      </header>}

      <main className={isLanding ? "landing-main" : undefined}>{children}</main>
    </div>
  );
}
