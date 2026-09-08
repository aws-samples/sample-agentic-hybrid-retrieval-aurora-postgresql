import { api } from "./api";
import { cachedRequest } from "./cachedRequest";

export function createDiscoverData() {
  return { scope: cachedRequest(() => api.readiness()) };
}

export const discoverData = createDiscoverData();

/** Share the live search-scope read across initial arrival and return navigation. */
export function preloadDiscover() {
  void discoverData.scope.load().catch(() => {});
}
