import type { ReactNode } from "react";

/**
 * One lesson a participant must carry out of the column it sits under.
 *
 * Rendered before and after a run, because the run proves the line and the
 * line names what the run proved. The same sentences are on the opening
 * slides, so five presenters and one screen say the same thing.
 */
export function KeepInMind({ children }: { children: ReactNode }) {
  return <aside className="inspector-keep" aria-label="Keep in mind"><span className="inspector-keep-label" aria-hidden="true">Keep in mind</span><p>{children}</p></aside>;
}
