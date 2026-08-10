/**
 * Fusion labelling, driven by what the run reports rather than by what a page assumes.
 *
 * A page previously read "Weighted RRF" while the served path was unweighted. The
 * label is now derived from `diagnostics.strategy`, so if the default is ever
 * flipped to the weighted function the copy follows the data — and until then it
 * cannot claim weighting that did not happen.
 */

const WEIGHTED_MARKER = "weighted";

/** True when the run that produced these diagnostics used weighted fusion. */
export function isWeightedFusion(strategy?: string | null): boolean {
  return (strategy ?? "").toLowerCase().includes(WEIGHTED_MARKER);
}

/**
 * Human label for the fusion method a run used.
 *
 * With no strategy the neutral name is returned: absent evidence must not render
 * as a claim in either direction.
 */
export function fusionLabel(strategy?: string | null): string {
  if (strategy == null) return "Reciprocal rank fusion";
  return isWeightedFusion(strategy)
    ? "Weighted reciprocal rank fusion"
    : "Reciprocal rank fusion";
}
