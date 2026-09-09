import { lazy, Suspense, useEffect, useRef } from "react";
import { Redirect, Route, Switch, useLocation, useSearch } from "wouter";
import { CommerceProvider } from "./commerce";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { Shell } from "./components/Shell";
import { PLAYGROUND_TABS, RETRIEVAL_SURFACE } from "./navigation";

const CatalogPage = lazy(() =>
  import("./pages/CatalogPage").then(({ CatalogPage: Page }) => ({ default: Page })),
);
const DiscoverPage = lazy(() =>
  import("./pages/DiscoverPage").then(({ DiscoverPage: Page }) => ({ default: Page })),
);
const PerformancePage = lazy(() =>
  import("./pages/ScaleInspectorPage").then(({ ScaleInspectorPage: Page }) => ({ default: Page })),
);
const ProductPage = lazy(() =>
  import("./pages/ProductPage").then(({ ProductPage: Page }) => ({ default: Page })),
);
const RetrievalLabPage = lazy(() =>
  import("./pages/PlaygroundPage").then(({ PlaygroundPage: Page }) => ({ default: Page })),
);
const SessionMemoryPage = lazy(() =>
  import("./pages/SessionMemoryPage").then(({ SessionMemoryPage: Page }) => ({ default: Page })),
);

function titleForPath(pathname: string): string {
  if (pathname === "/" || pathname === "/discover") return "Discover | Mosaic";
  if (pathname === "/catalog") return "Shop | Mosaic";
  if (pathname.startsWith("/products/")) return "Product details | Mosaic";
  const tab = PLAYGROUND_TABS.find((item) => item.path === pathname);
  if (tab) return `${tab.label} | Mosaic`;
  return "Mosaic";
}

function RouteAlias({ to }: { to: string }) {
  const search = useSearch();
  return <Redirect to={`${to}${search ? `?${search}` : ""}${window.location.hash}`} replace />;
}

function RoutedSurface() {
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const previousPathname = useRef(pathname);

  useEffect(() => {
    document.title = titleForPath(pathname);
    if (previousPathname.current !== pathname) {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
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
          {/* Same reason as /playground below: the name in the navigation has to
              be typeable. Two of the three nav labels already were -- /discover
              resolves and /playground redirects -- while /shop fell through to
              the catch-all and dropped the participant on Discover with nothing
              said. The canonical path stays /catalog, which is what the workshop
              instructions deep-link to. */}
          <Route path="/shop">
            <RouteAlias to="/catalog" />
          </Route>
          <Route path="/mosaic-labs/hnsw" component={PerformancePage} />
          <Route path="/mosaic-labs/memory" component={SessionMemoryPage} />
          <Route path="/mosaic-labs/studio">
            <RouteAlias to={RETRIEVAL_SURFACE.path} />
          </Route>
          <Route path="/mosaic-labs">
            <RouteAlias to={RETRIEVAL_SURFACE.path} />
          </Route>
          <Route path="/inspiration">
            <RouteAlias to={RETRIEVAL_SURFACE.path} />
          </Route>
          <Route path="/products/:productId" component={ProductPage} />
          <Route path="/labs/retrieval" component={RetrievalLabPage} />
          {/* The surface is named Playground in navigation, so the name is
              typeable. The canonical path stays /labs/retrieval, which is what
              the workshop instructions deep-link to. */}
          <Route path="/playground">
            <RouteAlias to={RETRIEVAL_SURFACE.path} />
          </Route>
          <Route path="/labs/performance">
            <RouteAlias to="/mosaic-labs/hnsw" />
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
