import { useEffect, useState } from "react";
import { stagesFor, type AssistExecutionPath, type AssistStage } from "./types";

/**
 * Minimum reading beat when the service outruns the interface.
 *
 * Real tool calls normally take longer than this. The dwell only matters when
 * several SSE milestones land in one React batch, where it prevents the middle
 * phases from being skipped without turning the progress into a second wait.
 */
export const stageDwellMs = 700;

/** The phase the progress presents: the actual one, reached no faster than one dwell per phase. */
export function useProgressiveStage(
  executionPath: AssistExecutionPath,
  actualStage: AssistStage | null,
  instant: boolean,
): AssistStage {
  const stages = stagesFor(executionPath);
  const [presentedStage, setPresentedStage] = useState<AssistStage>(() => {
    const actualIndex = actualStage
      ? stages.findIndex((stage) => stage.id === actualStage)
      : -1;
    return instant && actualIndex >= 0
      ? stages[actualIndex].id
      : stages[0].id;
  });
  const presentedIndex = Math.max(
    0,
    stages.findIndex((stage) => stage.id === presentedStage),
  );
  const matchedActualIndex = actualStage
    ? stages.findIndex((stage) => stage.id === actualStage)
    : -1;
  const actualIndex = matchedActualIndex >= 0
    ? matchedActualIndex
    : presentedIndex;

  useEffect(() => {
    if (actualIndex <= presentedIndex) return;
    if (instant) {
      setPresentedStage(stages[actualIndex].id);
      return;
    }
    const timer = window.setTimeout(() => {
      setPresentedStage(stages[Math.min(presentedIndex + 1, actualIndex)].id);
    }, stageDwellMs);
    return () => window.clearTimeout(timer);
  }, [actualIndex, instant, presentedIndex, stages]);

  return stages[presentedIndex].id;
}
