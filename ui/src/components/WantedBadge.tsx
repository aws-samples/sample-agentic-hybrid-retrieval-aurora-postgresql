import type { WantedProduct } from "../labOutcome";

/**
 * The lab's wanted product, marked by where it stands: green at its target
 * rank, orange when returned lower, grey when the run did not return it. The
 * position is the one the response served.
 */
export function WantedBadge({ wanted }: { wanted: WantedProduct }) {
  const where = wanted.tier === "missing"
    ? "not in these results"
    : wanted.finalRank === null ? "in these results" : `final #${wanted.finalRank}`;
  return <span className="shop-wanted-badge" data-tier={wanted.tier}>Wanted · {where}</span>;
}
