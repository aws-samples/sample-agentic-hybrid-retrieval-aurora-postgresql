import { ReactNode, useCallback, useEffect, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { useCommerce } from "../commerce";
import { hasSeenTour, PLAYGROUND_TOUR_KEY, PLAYGROUND_TOUR_STEPS } from "../tour";
import { CommerceDrawer } from "./CommerceDrawer";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";
import { SpotlightTour } from "./SpotlightTour";
import { HintsContext } from "../useHint";

/**
 * Storefront chrome. The reference boards read as a catalog first and an
 * instrument second, so shopper navigation sits in one header on every surface
 * and the landing only changes what is under it.
 */
export function Shell(
  { children, autoStartTour = false }: { children: ReactNode; autoStartTour?: boolean },
) {
  const [location, navigate] = useLocation();
  const search = useSearch();
  const pathname = location.split("?")[0];
  const onShopLanding = pathname === "/catalog" && search === "";
  const onPlayground = pathname === "/labs/retrieval";
  const [tourOpen, setTourOpen] = useState(false);
  const [playgroundTourOpen, setPlaygroundTourOpen] = useState(false);
  // The Playground has its own short tour: once per browser, on the first visit.
  useEffect(() => {
    if (autoStartTour && onPlayground && !hasSeenTour(PLAYGROUND_TOUR_KEY)) setPlaygroundTourOpen(true);
  }, [autoStartTour, onPlayground]);
  /**
   * The tour's stops are on Shop's landing and in the header, so it always runs
   * there. It offers itself once per browser, on the first visit to the landing.
   */
  useEffect(() => {
    if (autoStartTour && onShopLanding && !hasSeenTour()) setTourOpen(true);
  }, [autoStartTour, onShopLanding]);
  const startTour = useCallback(() => {
    if (onPlayground) {
      setPlaygroundTourOpen(true);
      return;
    }
    if (!onShopLanding) navigate("/catalog");
    setTourOpen(true);
  }, [navigate, onPlayground, onShopLanding]);
  const endTour = useCallback(() => setTourOpen(false), []);
  /**
   * The Playground and the HNSW instrument carry their own chrome and end in a
   * measurement, not an invitation to buy. A payment-methods band under a query
   * plan would be the one incoherent thing on those surfaces, so the storefront
   * footer belongs to the storefront: Shop, search, product pages.
   */
  const isInstrument = pathname.startsWith("/labs/")
    || pathname.startsWith("/mosaic-labs");
  // The preview supplies its own sources; the storefront footer describes synthetic products.
  const isCatalogPreview = import.meta.env.DEV && pathname === "/catalog-preview";
  const isStudioPrototype = import.meta.env.DEV && pathname === "/design-studio";
  const { isCartOpen } = useCommerce();

  return (
    <HintsContext.Provider value={autoStartTour}>
      <div className="app-shell">
        <a
          className="skip-link"
          href="#main-content"
          inert={isCartOpen || undefined}
          aria-hidden={isCartOpen || undefined}
        >
          Skip to main content
        </a>
        {isStudioPrototype ? null : <SiteHeader inert={isCartOpen} onStartTour={startTour} />}
        <main
          id="main-content"
          className="app-main"
          tabIndex={-1}
          inert={isCartOpen || undefined}
          aria-hidden={isCartOpen || undefined}
        >
          {children}
        </main>
        {/* Outside `main`, because a site footer is a sibling landmark rather than
            part of the surface's own content. It takes the same inert treatment as
            the header so the cart drawer is the only thing reachable while open. */}
        {isInstrument || isCatalogPreview || isStudioPrototype ? null : <SiteFooter inert={isCartOpen} />}
        <CommerceDrawer />
        <SpotlightTour open={tourOpen} onClose={endTour} />
        <SpotlightTour open={playgroundTourOpen} onClose={() => setPlaygroundTourOpen(false)} steps={PLAYGROUND_TOUR_STEPS} storageKey={PLAYGROUND_TOUR_KEY} />
      </div>
    </HintsContext.Provider>
  );
}
