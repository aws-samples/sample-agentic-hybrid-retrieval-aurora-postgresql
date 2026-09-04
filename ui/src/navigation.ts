import {
  useLocation,
  useSearchParams as useWouterSearchParams,
} from "wouter";
import { isPlausibleSearchEventId } from "./repairEvidence";

type NavigationOptions = {
  replace?: boolean;
};

/**
 * The retrieval surface's route and the one name for it.
 *
 * Three places spelled this name and they disagreed: the header said "Retrieval
 * Observatory", the Labs tab strip said the same, and the Discover band's kicker
 * said "Mosaic Labs" directly above a button reading "Open Retrieval
 * Observatory" — three names for one destination, two of them on one screen.
 *
 * One name now, and it is a participant-facing one. "Observatory" described the
 * instrument; "Playground" describes what a participant does here, and it is the
 * third and last entry in `Discover | Shop | Playground`. `label` is what
 * navigation prints, `title` is what the surface's own masthead prints, and
 * `headline` is the promise underneath it.
 */
export const RETRIEVAL_SURFACE = {
  path: "/labs/retrieval",
  label: "Playground",
  title: "Mosaic Playground",
  headline: "See how retrieval becomes a recommendation.",
} as const;

export function useNavigate() {
  const [, navigate] = useLocation();
  return (to: string, options?: NavigationOptions) => navigate(to, options);
}

export function useSearchParams(): [
  URLSearchParams,
  (params: URLSearchParams, options?: NavigationOptions) => void,
] {
  const [params, setParams] = useWouterSearchParams();
  return [params, setParams];
}

/**
 * The eligibility gates a Shop request can hand to the Playground.
 *
 * Enumerated rather than passed through, because the two ends have to agree: the
 * Playground rebuilds `SearchFilters` from these names, so a gate Shop puts on the
 * URL under a name not in this list would be silently dropped and the Playground
 * would retrieve a wider pool than Shop did.
 */
const FORWARDED_STRING_FILTERS = [
  "domain",
  "category_key",
  "brand",
  "availability",
] as const;

const FORWARDED_NUMBER_FILTERS = [
  "min_price_cents",
  "max_price_cents",
  "min_rating",
] as const;

/**
 * The Playground link that carries a shopper's own words with it.
 *
 * Shop's "See how this was retrieved" needs the query and the eligibility gates
 * that were actually in force, or the Playground would re-run a different
 * request and the participant would compare two unrelated result sets. The
 * scenario picker stays on its default; `q` is what overrides the query it
 * would otherwise seed.
 *
 * `searchEventId` carries the run itself rather than the recipe for one. Query
 * and gates are enough to ask for an equivalent request, but re-asking mints a
 * second `mosaic.search_event`, and the run whose results the shopper is looking
 * at is then unreachable: no later comparison can anchor on what Shop served.
 */
export function playgroundQueryHref(
  query: string,
  filters: Record<string, unknown> = {},
  searchEventId?: string | null,
): string {
  const params = new URLSearchParams({ q: query });
  for (const name of FORWARDED_STRING_FILTERS) {
    const value = filters[name];
    if (typeof value === "string" && value) params.set(name, value);
  }
  // Zero is not a gate on any of the three numeric bounds: a 0 price floor, a 0
  // rating floor and a 0 ceiling all mean "unset", and Shop's own chip row already
  // treats them that way. Forwarding `min_rating=0` would read as a constraint the
  // shopper chose.
  for (const name of FORWARDED_NUMBER_FILTERS) {
    const value = filters[name];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      params.set(name, String(value));
    }
  }
  if (filters.in_stock_only === true) params.set("in_stock_only", "true");
  const event = searchEventId?.trim();
  if (event) params.set("event", event);
  return `${RETRIEVAL_SURFACE.path}?${params}`;
}

/**
 * The Shop run the link points at, when it points at one that could exist.
 *
 * Shape-checked here rather than on arrival at the API, so a hand-edited link or
 * a preview-only placeholder id falls back to replaying the query instead of
 * spending a request and reporting a run the Playground never read. `null` is
 * the honest answer for "no run was carried", which is what keeps the plain
 * query hand-off working unchanged.
 */
export function forwardedSearchEvent(params: URLSearchParams): string | null {
  const value = params.get("event")?.trim() ?? "";
  return isPlausibleSearchEventId(value) ? value : null;
}

/**
 * Rebuild the forwarded gates, so the Playground runs the request Shop ran.
 *
 * Returns an empty object when nothing was forwarded, which is what makes an
 * unconstrained hand-off retrieve the whole catalog rather than inheriting whatever
 * the currently selected scenario happens to constrain.
 */
export function forwardedSearchFilters(
  params: URLSearchParams,
): Record<string, string | number | boolean> {
  const filters: Record<string, string | number | boolean> = {};
  for (const name of FORWARDED_STRING_FILTERS) {
    const value = params.get(name);
    if (value) filters[name] = value;
  }
  for (const name of FORWARDED_NUMBER_FILTERS) {
    const raw = params.get(name);
    if (!raw) continue;
    const value = Number(raw);
    // Rejected at both ends, so a hand-crafted `?min_rating=0` cannot introduce a
    // gate the link would never have written.
    if (Number.isFinite(value) && value > 0) filters[name] = value;
  }
  if (params.get("in_stock_only") === "true") filters.in_stock_only = true;
  return filters;
}
