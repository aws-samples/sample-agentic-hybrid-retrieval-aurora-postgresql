import { ReactNode } from "react";
import { useLocation } from "wouter";
import { useCommerce } from "../commerce";
import { CommerceDrawer } from "./CommerceDrawer";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/**
 * Storefront chrome. The reference boards read as a catalog first and an
 * instrument second, so shopper navigation sits in one header on every surface
 * and the landing only changes what is under it.
 */
export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const isLanding = pathname === "/" || pathname === "/discover";
  /**
   * The Playground and the HNSW instrument carry their own chrome and end in a
   * measurement, not an invitation to buy. A payment-methods band under a query
   * plan would be the one incoherent thing on those surfaces, so the storefront
   * footer belongs to the storefront: Discover, Shop, search, product pages.
   */
  const isInstrument = pathname.startsWith("/labs/")
    || pathname.startsWith("/mosaic-labs");
  const { isCartOpen } = useCommerce();

  return (
    <div className={isLanding ? "app-shell landing-shell" : "app-shell"}>
      <a
        className="skip-link"
        href="#main-content"
        inert={isCartOpen || undefined}
        aria-hidden={isCartOpen || undefined}
      >
        Skip to main content
      </a>
      <SiteHeader inert={isCartOpen} />
      <main
        id="main-content"
        className={isLanding ? "app-main landing-main" : "app-main"}
        tabIndex={-1}
        inert={isCartOpen || undefined}
        aria-hidden={isCartOpen || undefined}
      >
        {children}
      </main>
      {/* Outside `main`, because a site footer is a sibling landmark rather than
          part of the surface's own content. It takes the same inert treatment as
          the header so the cart drawer is the only thing reachable while open. */}
      {isInstrument ? null : <SiteFooter inert={isCartOpen} />}
      <CommerceDrawer />
    </div>
  );
}
