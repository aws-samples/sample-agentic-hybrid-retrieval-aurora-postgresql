import { Redirect, Route, Switch } from "wouter";
import { CommerceProvider } from "./commerce";
import { Shell } from "./components/Shell";
import { CatalogPage } from "./pages/CatalogPage";
import { DiscoverPage } from "./pages/DiscoverPage";
import { MosaicLabsPage } from "./pages/MosaicLabsPage";
import { PerformancePage } from "./pages/PerformancePage";
import { ProductPage } from "./pages/ProductPage";
import { RetrievalLabPage } from "./pages/RetrievalLabPage";
import { SearchPage } from "./pages/SearchPage";

export function App() {
  return (
    <CommerceProvider>
      <Shell>
        <Switch>
          <Route path="/" component={DiscoverPage} />
          <Route path="/discover" component={DiscoverPage} />
          <Route path="/catalog" component={CatalogPage} />
          <Route path="/search" component={SearchPage} />
          <Route path="/mosaic-labs" component={MosaicLabsPage} />
          <Route path="/inspiration">
            <Redirect to="/mosaic-labs" replace />
          </Route>
          <Route path="/products/:productId" component={ProductPage} />
          <Route path="/labs/retrieval" component={RetrievalLabPage} />
          <Route path="/labs/performance" component={PerformancePage} />
          <Route>
            <Redirect to="/" replace />
          </Route>
        </Switch>
      </Shell>
    </CommerceProvider>
  );
}
