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
  headline:
    "A search can return a plausible top result while the system behind it is wrong.",
} as const;

/** Keep tab names, footer destinations and browser titles in the same order. */
export const PLAYGROUND_TABS = [
  { id: "retrieval", path: RETRIEVAL_SURFACE.path, label: "Hybrid retrieval" },
  { id: "hnsw", path: "/mosaic-labs/hnsw", label: "Scale & HNSW" },
  { id: "memory", path: "/mosaic-labs/memory", label: "Session & Memory" },
] as const;

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
 * Scalar gates carried between surfaces. Attribute maps are encoded as JSON
 * and compared structurally, so their key order cannot change a lab verdict.
 */
export const FORWARDABLE_FILTER_KEYS = [
  ...FORWARDED_STRING_FILTERS,
  ...FORWARDED_NUMBER_FILTERS,
  "in_stock_only",
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
  const attributes = filters.attributes;
  if (attributes && typeof attributes === "object" && !Array.isArray(attributes)
    && Object.keys(attributes).length > 0) {
    params.set("attributes", JSON.stringify(attributes));
  }
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
 * The agent run a Lab 3 hand-off carries back from Shop.
 *
 * Lab 3's own link sends the participant to Shop -- `retrievalExampleHref`
 * routes a `reason` mission to `shopMissionHref` -- because the agent lives
 * there. Nothing carried the answer back, so the Playground's Prove stage,
 * which is the only thing that can grade Lab 3, held an `agentRunId` that only
 * its own Reason stage could fill. A participant who did the exercise where the
 * product told them to had to run the agent a second time to be graded on it,
 * paying for another model invocation to prove work already finished.
 *
 * Shape-checked here, exactly as a carried search event is, so a hand-edited
 * link falls back to "no run carried" rather than spending a proof request. The
 * id is not trusted beyond its shape: `POST /api/labs/3/proof` reads the
 * persisted run and remains the authority on whether it proves anything.
 */
export function forwardedAgentRun(params: URLSearchParams): string | null {
  const value = params.get("run")?.trim() ?? "";
  return isPlausibleSearchEventId(value) ? value : null;
}

/**
 * The Playground link that grades one finished agent run.
 *
 * Built here beside the hand-off it mirrors, so Shop cannot encode the return
 * trip one way while the Playground reads it another.
 */
export function playgroundProofHref(missionId: string, agentRunId: string): string {
  const params = new URLSearchParams({ example: missionId, run: agentRunId });
  return `${RETRIEVAL_SURFACE.path}?${params}`;
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
): Record<string, unknown> {
  const filters: Record<string, unknown> = {};
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
  try {
    const attributes: unknown = JSON.parse(params.get("attributes") ?? "null");
    if (attributes && typeof attributes === "object" && !Array.isArray(attributes)
      && Object.keys(attributes).length > 0) {
      filters.attributes = attributes;
    }
  } catch {
    // A hand-edited URL must not crash the search surface.
  }
  return filters;
}

/** Accept only a same-site Shop path as a product's return destination. */
export function catalogReturnPath(value: string | null): string | null {
  if (!value?.startsWith("/catalog")) return null;
  try {
    const url = new URL(value, "https://mosaic.invalid");
    return url.origin === "https://mosaic.invalid" && url.pathname === "/catalog"
      ? url.pathname + url.search
      : null;
  } catch {
    return null;
  }
}

/** Carry the original Shop context through successive product-page visits. */
export function productDetailHref(productId: number): string {
  const current = window.location;
  const from = current.pathname === "/catalog"
    ? current.pathname + current.search
    : catalogReturnPath(new URLSearchParams(current.search).get("from"));
  return `/products/${productId}${from ? `?${new URLSearchParams({ from })}` : ""}`;
}
