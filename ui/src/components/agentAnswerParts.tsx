import { Search } from "lucide-react";
import {
  formatAvailability,
  formatCategoryKey,
  formatPriceCompact,
} from "../format";
import { domainLabels } from "../media";
import type { AgentPlanStep, SearchFilters } from "../types";

/**
 * The two parts of an agent run that read the same way wherever the run is shown:
 * the filters retrieval enforced, and the searches that were issued.
 *
 * Both are read straight off `AgentResponse.plan`, so Shop and the Playground
 * print the same executed plan rather than two descriptions of it. They live
 * here because the Playground's Reason stage needs them too, and a second copy
 * would be a second thing to keep true.
 */

/**
 * The constraints one agent search resolved, as chips.
 *
 * `plan[].filters` is the merged `SearchFilters` the service passed to
 * retrieval, so every chip here is a constraint that ran against the catalog -
 * both the ones the request implied and the ones Shop already had active.
 */
function describeFilters(filters: SearchFilters): string[] {
  // A zero price bound or a zero rating is not a constraint, so the falsy
  // numbers `&&` short-circuits to are dropped by the filter below with the rest.
  const chips: Array<string | number | false | undefined> = [
    filters.domain && domainLabels[filters.domain],
    filters.category_key && formatCategoryKey(filters.category_key),
    filters.brand,
    ...(filters.brands ?? []),
    filters.min_price_cents && `Over ${formatPriceCompact(filters.min_price_cents)}`,
    filters.max_price_cents && `Under ${formatPriceCompact(filters.max_price_cents)}`,
    filters.min_rating && `${filters.min_rating}+ stars`,
    filters.availability && formatAvailability(filters.availability),
    filters.in_stock_only && "In stock only",
    filters.include_refurbished && "Refurbished included",
    filters.include_sponsored && "Sponsored included",
    ...Object.entries(filters.attributes ?? {}).map(
      ([name, value]) => `${name.replace(/_/g, " ")} ${String(value)}`,
    ),
  ];
  return chips.filter((chip): chip is string => Boolean(chip));
}

/**
 * The constraints that actually ran, surfaced at the Interpret position.
 *
 * The union of `plan[].filters` across the searches the agent issued - each
 * chip is a constraint retrieval enforced against the catalog, deduplicated
 * across steps. The reference design labeled invented chips "extracted";
 * these are the extracted ones, read back from the executed plan.
 */
export function Criteria({ plan }: { plan: AgentPlanStep[] }) {
  const chips = Array.from(
    new Set(plan.flatMap((step) => describeFilters(step.filters))),
  );
  if (!chips.length) return null;
  return (
    <section className="ask-mosaic-criteria">
      <h3>Filters I searched with</h3>
      <ul aria-label="Filters Mosaic searched with">
        {chips.map((chip) => (
          <li key={chip}>{chip}</li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The searches behind the shortlist, which the panel used to fetch and then
 * drop on the floor. `plan` holds one entry per search that returned
 * evidence-backed products, so this is how the request became catalog
 * constraints - the honest form of the reference design's "based on your
 * workspace and past views", which describes personalisation this system does
 * not do.
 */
export function Searches({ plan }: { plan: AgentPlanStep[] }) {
  return (
    <details className="ask-mosaic-receipt ask-mosaic-search-receipt">
      <summary>
        <Search size={18} />
        How I searched
        <span>{plan.length}</span>
      </summary>
      <ol className="ask-mosaic-searches">
        {plan.map((step, index) => (
          <li key={`${index}-${step.query}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{step.query}</strong>
              <small>{step.purpose || "No filters beyond your words"}</small>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
