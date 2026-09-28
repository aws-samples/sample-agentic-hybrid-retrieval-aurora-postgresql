import { useEffect, useState } from "react";
import { catalogData, type BrowseRequest } from "./catalogData";
import type { CatalogPage, SearchFilters } from "./types";

type FacetName = "category_key" | "brand";
type FacetOption = CatalogPage["facets"][string][number];

/**
 * One filter menu's options: every other filter applied, never its own.
 *
 * The server counts facets under every filter, so a menu read from the
 * visible page lists only its current choice once one is made, and a search
 * loads no browse page at all, which left the Category menu holding nothing
 * but "All products". Each menu asks the cached browse endpoint with its own
 * filter removed, and only while the filter sheet is open, so no search waits
 * on it.
 *
 * Args:
 *   facet: The menu to fill.
 *   pageOptions: The visible browse page's facet, or null during a search.
 *   open: Whether the filter sheet is showing.
 */
export function useFacetOptions(
  facet: FacetName,
  {
    dataset,
    filters,
    pageOptions,
    open,
  }: {
    dataset: string | null;
    filters: SearchFilters;
    pageOptions: FacetOption[] | null;
    open: boolean;
  },
): FacetOption[] {
  const request: BrowseRequest = {
    dataset,
    filters: { ...filters, [facet]: undefined },
    offset: 0,
    limit: 1,
    sort: "featured",
    // A search spans the whole catalog, not the featured browse collection.
    collection: "all",
  };
  const key = JSON.stringify(request);
  const needed = open && (!pageOptions || Boolean(filters[facet]));
  const [loaded, setLoaded] = useState<{ key: string; options: FacetOption[] } | null>(null);

  useEffect(() => {
    if (!needed) return undefined;
    const cached = catalogData.peek(request);
    if (cached) {
      setLoaded({ key, options: cached.facets[facet] ?? [] });
      return undefined;
    }
    let current = true;
    catalogData
      .load(request)
      .then((page) => {
        if (current) setLoaded({ key, options: page.facets[facet] ?? [] });
      })
      // The menu keeps "All products" and whatever the page offered; a failed
      // menu read is not a failed search.
      .catch(() => {});
    return () => {
      current = false;
    };
    // `key` is the request, serialized; `request` itself is rebuilt each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, needed, facet]);

  if (loaded?.key === key) return loaded.options;
  return pageOptions ?? [];
}
