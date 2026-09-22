import { api } from "./api";
import { cachedRequest } from "./cachedRequest";
import type { CatalogPage, SearchFilters } from "./types";

export type BrowseRequest = {
  dataset: string | null;
  filters: SearchFilters;
  offset: number;
  limit?: number;
  sort: string;
  collection: "workspace" | "all";
};

/** Browse pages can be reused briefly; searches and lab checks stay fresh. */
export function createCatalogData() {
  const pages = new Map<string, ReturnType<typeof cachedRequest<CatalogPage>>>();

  function entry(input: BrowseRequest) {
    const key = JSON.stringify(input);
    const existing = pages.get(key);
    if (existing) {
      pages.delete(key);
      pages.set(key, existing);
      return existing;
    }
    const page = cachedRequest(() => api.catalog(
      input.filters, input.offset, input.limit, input.sort, input.collection,
    ));
    pages.set(key, page);
    while (pages.size > 32) pages.delete(pages.keys().next().value!);
    return page;
  }

  return {
    peek: (input: BrowseRequest) => entry(input).peek(),
    load: (input: BrowseRequest) => entry(input).load(),
    clear: () => pages.clear(),
  };
}

export const catalogData = createCatalogData();
