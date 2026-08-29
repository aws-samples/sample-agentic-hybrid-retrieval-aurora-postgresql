import { lazy, Suspense, useEffect, useRef } from "react";
import { Redirect, Route, Switch, useLocation } from "wouter";
import { CommerceProvider } from "./commerce";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { Shell } from "./components/Shell";

const CatalogPage = lazy(() =>
  import("./pages/CatalogPage").then(({ CatalogPage: Page }) => ({ default: Page })),
);
const DiscoverPage = lazy(() =>
  import("./pages/DiscoverPage").then(({ DiscoverPage: Page }) => ({ default: Page })),
);
const MosaicStudioPage = lazy(() =>
  import("./pages/MosaicStudioPage").then(({ MosaicStudioPage: Page }) => ({ default: Page })),
);
const PerformancePage = lazy(() =>
  import("./pages/PerformancePage").then(({ PerformancePage: Page }) => ({ default: Page })),
);
const ProductPage = lazy(() =>
  import("./pages/ProductPage").then(({ ProductPage: Page }) => ({ default: Page })),
);
const RetrievalLabPage = lazy(() =>
  import("./pages/RetrievalLabPage").then(({ RetrievalLabPage: Page }) => ({ default: Page })),
);
const SearchPage = lazy(() =>
  import("./pages/SearchPage").then(({ SearchPage: Page }) => ({ default: Page })),
);

function titleForPath(pathname: string): string {
  if (pathname === "/" || pathname === "/discover") return "Discover | Mosaic";
  if (pathname === "/catalog") return "Shop | Mosaic";
  if (pathname === "/search") return "Search | Mosaic";
  if (pathname.startsWith("/products/")) return "Product details | Mosaic";
  if (pathname === "/labs/retrieval") return "Playground | Mosaic";
  if (pathname === "/mosaic-labs/hnsw") return "Vector index at scale | Mosaic";
  if (pathname === "/mosaic-labs/studio") return "Catalog studio | Mosaic";
  return "Mosaic";
}

function RoutedSurface() {
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const previousPathname = useRef(pathname);

  useEffect(() => {
    document.title = titleForPath(pathname);
    if (previousPathname.current !== pathname) {
      document.getElementById("main-content")?.focus({ preventScroll: true });
    }
    previousPathname.current = pathname;
  }, [pathname]);

  return (
    <RouteErrorBoundary resetKey={pathname}>
      <Suspense
        fallback={<p className="route-loading" role="status">Loading Mosaic...</p>}
      >
        <Switch>
          <Route path="/" component={DiscoverPage} />
          <Route path="/discover" component={DiscoverPage} />
          <Route path="/catalog" component={CatalogPage} />
          <Route path="/search" component={SearchPage} />
          <Route path="/mosaic-labs/hnsw" component={PerformancePage} />
          <Route path="/mosaic-labs/studio" component={MosaicStudioPage} />
          <Route path="/mosaic-labs">
            <Redirect to="/labs/retrieval" replace />
          </Route>
          <Route path="/inspiration">
            <Redirect to="/labs/retrieval" replace />
          </Route>
          <Route path="/products/:productId" component={ProductPage} />
          <Route path="/labs/retrieval" component={RetrievalLabPage} />
          {/* The surface is named Playground in navigation, so the name is
              typeable. The canonical path stays /labs/retrieval, which is what
              the workshop instructions deep-link to. */}
          <Route path="/playground">
            <Redirect to="/labs/retrieval" replace />
          </Route>
          <Route path="/labs/performance">
            <Redirect to="/mosaic-labs/hnsw" replace />
          </Route>
          <Route>
            <Redirect to="/" replace />
          </Route>
        </Switch>
      </Suspense>
    </RouteErrorBoundary>
  );
}

export function App() {
  return (
    <CommerceProvider>
      <Shell>
        {/* Inside Shell so the header and cart survive a failed surface, and
            outside Suspense so a rejected lazy import lands here rather than
            leaving the fallback on screen forever. */}
        <RoutedSurface />
      </Shell>
    </CommerceProvider>
  );
}
