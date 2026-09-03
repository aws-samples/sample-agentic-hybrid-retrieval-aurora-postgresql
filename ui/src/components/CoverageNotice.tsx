import { SearchX } from "lucide-react";

import type { QueryCoverage } from "../types";

import "./CoverageNotice.css";

/**
 * Says which words of a request the catalog does not carry.
 *
 * Renders for one state only. `grounded` needs no notice; `unavailable` means
 * the database cannot answer the question, and inventing a caveat from a
 * missing seed step would be a claim the run did not make. So an unmigrated or
 * unseeded deployment shows exactly what it showed before coverage existed.
 *
 * The results below this notice are neither hidden nor reordered. They are the
 * same rows in the same measured order; the notice exists because they answer a
 * narrower question than the one that was asked. A shopper searching for a
 * charger for model A2342 is better served by chargers under a caveat than by
 * an empty page, and much better served than by a confident match.
 */
export function CoverageNotice({ coverage }: { coverage?: QueryCoverage | null }) {
  if (!coverage || coverage.confidence !== "unanchored") {
    return null;
  }

  const terms = coverage.unmatched_terms;
  if (terms.length === 0) {
    return null;
  }

  return (
    <aside className="coverage-notice" role="status" data-testid="coverage-notice">
      <SearchX size={18} className="coverage-notice__icon" aria-hidden />
      <div className="coverage-notice__body">
        <p className="coverage-notice__lead">
          Nothing in the catalog matches{" "}
          {terms.map((term, index) => (
            <span key={term}>
              {index > 0 ? (index === terms.length - 1 ? " or " : ", ") : null}
              <span className="coverage-notice__term">{term}</span>
            </span>
          ))}
          .
        </p>
        <p className="coverage-notice__detail">
          The results below answer the rest of the request.
        </p>
      </div>
    </aside>
  );
}
