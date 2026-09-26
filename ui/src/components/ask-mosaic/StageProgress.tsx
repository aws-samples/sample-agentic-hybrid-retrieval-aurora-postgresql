import {
  Check,
  ChevronDown,
  CircleStop,
  GitCompareArrows,
  LoaderCircle,
  X,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import {
  focusedFollowUpStages,
  fullRetrievalStages,
  type AssistExecutionPath,
  type AssistStage,
} from "./types";

/**
 * Seconds elapsed on the step that is working, ticking.
 *
 * Wall clock against the moment the service announced the step, so this is a
 * measurement rather than a progress animation: nothing here estimates how much
 * longer the step will take, because nothing knows.
 */
function StageElapsed({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(() => Date.now() - since);

  useEffect(() => {
    setElapsed(Date.now() - since);
    const timer = window.setInterval(() => {
      setElapsed(Date.now() - since);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [since]);

  const seconds = Math.max(0, Math.floor(elapsed / 1000));
  if (seconds < 1) return null;
  return <small className="ask-mosaic-stage-elapsed">{seconds}s</small>;
}

export function StageRail({
  actualStage,
  cancelled = false,
  complete,
  executionPath,
  failed,
  presentedStage,
  stageDetail,
  stageStartedAt,
  panels,
  onPresentationProgress,
}: {
  actualStage: AssistStage | null;
  /** A reader-stopped run, not a failure: the step in progress freezes rather
   * than spinning forever, but is never called "Needs attention". */
  cancelled?: boolean;
  complete: boolean;
  executionPath: AssistExecutionPath;
  failed: boolean;
  presentedStage: AssistStage;
  stageDetail: string;
  stageStartedAt: number;
  panels: Partial<Record<AssistStage, ReactNode>>;
  onPresentationProgress?: () => void;
}) {
  const stages = executionPath === "focused_follow_up"
    ? focusedFollowUpStages
    : fullRetrievalStages;
  const actualIndex = complete
    ? stages.length
    : actualStage
    ? stages.findIndex((item) => item.id === actualStage)
    : 0;
  const presentedIndex = Math.max(
    0,
    stages.findIndex((item) => item.id === presentedStage),
  );
  const disrupted = failed || cancelled;
  return (
    <section className="ask-mosaic-timeline" aria-label="Retrieval activity">
      <p className="ask-mosaic-timeline-heading">
        <GitCompareArrows size={14} aria-hidden="true" />
        Retrieval activity
      </p>
      <ol className="ask-mosaic-progress" aria-label="Ask Mosaic activity">
        {stages.map((stage, index) => {
          const state: AssistStageState = index < presentedIndex
            ? "complete"
            : index > presentedIndex
              ? "pending"
              : disrupted
                ? "failed"
                : complete || index < actualIndex
                  ? "complete"
                  : "active";
          const stateLabel = state === "complete"
            ? "Complete"
            : state === "active"
              ? "In progress"
              : state === "failed"
                ? (cancelled ? "Stopped" : "Needs attention")
              : "Pending";
          const description = (state === "active" || state === "failed")
            && stage.id === actualStage
            && stageDetail
            ? stageDetail
            : stage.description;
          return (
            <li className={state} key={stage.id}>
              {/* Keeping labels inside the card preserves space for their text
                  and the comparison at narrow drawer widths. */}
              <span className="ask-mosaic-stage-rail">
                <span className="ask-mosaic-stage-node" aria-hidden="true">
                  {state === "complete"
                    ? <Check size={16} strokeWidth={2.25} />
                    : state === "active"
                      ? <LoaderCircle className="spin" size={16} />
                      : state === "failed"
                        ? (cancelled ? <CircleStop size={16} /> : <X size={16} />)
                      : index + 1}
                </span>
              </span>
              <StageDisclosure
                description={description}
                elapsedSince={
                  state === "active" && stage.id === actualStage && !complete
                    ? stageStartedAt
                    : null
                }
                label={stage.label}
                onPresentationProgress={onPresentationProgress}
                panel={panels[stage.id]}
                presented={index === presentedIndex}
                state={state}
                stateLabel={stateLabel}
                title={stage.title}
              />
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/**
 * Minimum reading beat when the service outruns the interface.
 *
 * Real tool calls normally take longer than this. The dwell only matters when
 * several SSE milestones land in one React batch, where it prevents the middle
 * steps from being skipped without turning the timeline into a second wait.
 */
export const stageDwellMs = 700;

export function useProgressiveStage(
  executionPath: AssistExecutionPath,
  actualStage: AssistStage | null,
  instant: boolean,
): AssistStage {
  const stages = executionPath === "focused_follow_up"
    ? focusedFollowUpStages
    : fullRetrievalStages;
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

type AssistStageState = "complete" | "active" | "failed" | "pending";

function StageDisclosure({
  description,
  elapsedSince,
  label,
  onPresentationProgress,
  panel,
  presented,
  state,
  stateLabel,
  title,
}: {
  description: string;
  /** When this step started, or null unless it is the one working. */
  elapsedSince: number | null;
  label: string;
  onPresentationProgress?: () => void;
  panel: ReactNode;
  /** This is the one stage the progressive timeline is currently presenting. */
  presented: boolean;
  state: AssistStageState;
  stateLabel: string;
  title: string;
}) {
  /**
   * Scope an explicit reader choice to the state in which it was made. A stage
   * changing from active to complete returns to the progressive default, while a
   * completed stage the reader reopens stays open as later stages arrive.
   */
  const [override, setOverride] = useState<{
    state: AssistStageState;
    open: boolean;
  } | null>(null);
  const reduceMotion = useReducedMotion();
  const hasPanel = Boolean(panel) && state !== "pending";
  const open = hasPanel && (
    override?.state === state ? override.open : presented
  );

  return (
    <section className="ask-mosaic-stage-panel">
      <button
        className="ask-mosaic-stage-summary"
        type="button"
        aria-expanded={hasPanel ? open : undefined}
        // Nothing to disclose yet: a pending stage has not run, and a stage that
        // is working has produced nothing until its first tool returns. The
        // control used to stay enabled and expanded through both, so an active
        // card opened onto an empty box.
        disabled={!hasPanel}
        onClick={() => {
          setOverride({ state, open: !open });
        }}
      >
        <span className="ask-mosaic-stage-copy">
          <span className="ask-mosaic-stage-eyebrow">
            <small className="ask-mosaic-stage-label">{label}</small>
            <small className="ask-mosaic-stage-state">{stateLabel}</small>
            {elapsedSince ? <StageElapsed since={elapsedSince} /> : null}
          </span>
          <strong>{title}</strong>
          <span className="ask-mosaic-stage-detail">{description}</span>
        </span>
        {hasPanel ? (
          <ChevronDown
            className={open
              ? "ask-mosaic-stage-chevron open"
              : "ask-mosaic-stage-chevron"}
            size={17}
          />
        ) : null}
      </button>
      {/* Height, not display. The content was mounted and unmounted outright, so
          a step folding itself away after its dwell snapped the whole panel up by
          however tall its result was. The padding and rule live on the inner
          element, or a collapsed panel would still draw 16px of them. */}
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="content"
            style={{ overflow: "hidden" }}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onAnimationComplete={onPresentationProgress}
            transition={reduceMotion
              ? { duration: 0 }
              : {
                duration: 0.24,
                ease: [0.23, 1, 0.32, 1],
                opacity: { duration: 0.16 },
              }}
          >
            <div className="ask-mosaic-stage-content">{panel}</div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
