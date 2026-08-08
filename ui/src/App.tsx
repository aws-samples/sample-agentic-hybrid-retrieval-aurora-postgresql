import { Redirect, Route, Switch } from "wouter";
import { Shell } from "./components/Shell";
import { CatalogPage } from "./pages/CatalogPage";
import { DiscoverPage } from "./pages/DiscoverPage";
import { PerformancePage } from "./pages/PerformancePage";
import { ProductPage } from "./pages/ProductPage";
import { RetrievalLabPage } from "./pages/RetrievalLabPage";
import { SearchPage } from "./pages/SearchPage";

export function App() {
  return (
    <Shell>
      <Switch>
        <Route path="/" component={DiscoverPage} />
        <Route path="/discover" component={DiscoverPage} />
        <Route path="/catalog" component={CatalogPage} />
        <Route path="/search" component={SearchPage} />
        <Route path="/products/:productId" component={ProductPage} />
        <Route path="/labs/retrieval" component={RetrievalLabPage} />
        <Route path="/labs/performance" component={PerformancePage} />
        <Route>
          <Redirect to="/" replace />
        </Route>
      </Switch>
    </Shell>
  );
}
