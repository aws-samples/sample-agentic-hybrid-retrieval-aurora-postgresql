import type { SearchFilters } from "./types";
import { useEffect, useState } from "react";

type CatalogSource = { dataset_id: string | null; real: boolean; loaded?: boolean };
let pending: Promise<CatalogSource> | undefined;
let received: CatalogSource | undefined;

/** One runtime read shared by the storefront's source labels and controls. */
export function useCatalogSource(): CatalogSource {
  const [source, setSource] = useState<CatalogSource>(() => received ?? { dataset_id: null, real: false, loaded: false });
  useEffect(() => {
    let active = true;
    pending ??= Promise.resolve().then(() => fetch("/api/catalog/source")).then(async (response) => {
      if (!response.ok) throw new Error("Catalog source unavailable");
      const value = await response.json() as { dataset_id: string | null };
      received = { dataset_id: value.dataset_id, real: Boolean(value.dataset_id), loaded: true };
      return received;
    }).catch(() => { pending = undefined; return { dataset_id: null, real: false, loaded: true }; });
    void pending.then((value) => { if (active) setSource(value); });
    return () => { active = false; };
  }, []);
  return source;
}

export function sourceFilters(filters: SearchFilters, real: boolean): SearchFilters {
  if (!real) return filters;
  const categories: Record<string, { category_key: string; domain: SearchFilters["domain"] }> = {
    "over-ear-headphones": { category_key: "headphones", domain: "consumer_electronics" },
    "mesh-office-chairs": { category_key: "chair", domain: "home_office" },
    "ergonomic-office-chairs": { category_key: "chair", domain: "home_office" },
    "productivity-monitors": { category_key: "monitor", domain: "consumer_electronics" },
    "ultrawide-monitors": { category_key: "monitor", domain: "consumer_electronics" },
  };
  const category = categories[filters.category_key ?? ""];
  return category
    ? { ...filters, category_key: category.category_key, domain: filters.domain ?? category.domain }
    : filters;
}
