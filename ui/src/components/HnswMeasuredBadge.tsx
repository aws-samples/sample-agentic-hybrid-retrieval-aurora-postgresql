import type { ReactNode } from "react";

type HnswMeasuredBadgeProps = {
  attributed: boolean;
  /** Extra qualifiers appended after the word, e.g. the A/B cluster conditions. */
  suffix?: ReactNode;
  /** Additional badge classes, e.g. `ab` for the controlled-pair variant. */
  className?: string;
};

/**
 * The one badge every panel that renders the committed HNSW artifact must use.
 *
 * Four panels on this page read the same file. Each had its own hardcoded
 * MEASURED, so the page could only ever make one claim about that file: that it
 * describes the cluster in front of you. It does not have to. The artifact
 * carries the corpus it was measured against and whether the worktree was clean
 * at the time, the server compares both against what is running, and the word
 * here follows that answer.
 *
 * Sharing the component is the point: four independent copies of the word could
 * disagree with each other about the same artifact on the same screen.
 */
export function HnswMeasuredBadge({
  attributed,
  suffix,
  className = "",
}: HnswMeasuredBadgeProps) {
  const classes = ["hnsw-evidence-badge", "measured", className, attributed ? "" : "elsewhere"]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes}>
      {attributed ? "MEASURED" : "MEASURED ELSEWHERE"}
      {suffix}
    </span>
  );
}
