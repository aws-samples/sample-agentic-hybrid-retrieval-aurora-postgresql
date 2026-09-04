/** Enough of a `search_event_id` to recognise on screen, without printing 36
 * characters. Lives here because the Playground prints run ids in two places:
 * this summary line and the carried-over banner above it. */
export function shortEventId(searchEventId: string): string {
  return searchEventId.slice(0, 8);
}

/**
 * One line of run bookkeeping above the numbered stages.
 *
 * Which run is on screen, which run this mission measures against, and the one
 * control that moves the second one. Extracted from the page so the surface
 * that owns the mission loop stays readable: the page decides what the two runs
 * are, this decides how they read.
 */
export function RunSummary({
  baselineSearchEventId,
  latestSearchEventId,
  onPinBaseline,
}: {
  /** The run this mission measures its repairs against, or null before one is
   * pinned. */
  baselineSearchEventId: string | null;
  /** The run this surface currently holds evidence for. Nothing is rendered
   * without one: there is no bookkeeping to do before the first run. */
  latestSearchEventId: string | null;
  /** Re-pin the baseline to the run on screen. */
  onPinBaseline: () => void;
}) {
  if (!latestSearchEventId) return null;

  return (
    <p className="labs-run-summary">
      <span>
        Run on screen <code>{shortEventId(latestSearchEventId)}</code>
      </span>
      <span>
        {baselineSearchEventId
          ? (
            <>
              Baseline <code>{shortEventId(baselineSearchEventId)}</code>
            </>
          )
          : "No baseline pinned"}
      </span>
      <button
        className="secondary-button"
        disabled={baselineSearchEventId === latestSearchEventId}
        onClick={onPinBaseline}
        type="button"
      >
        Pin as baseline
      </button>
    </p>
  );
}
