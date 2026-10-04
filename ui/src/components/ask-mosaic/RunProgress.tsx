import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { phaseFinding, type RunData } from "./findings";
import { stagesFor, type AssistStage } from "./types";

/**
 * Seconds the phase in progress has been working, ticking.
 *
 * Wall clock against the moment the service announced the phase, so this is a
 * measurement rather than an animation: nothing here estimates how much longer
 * the phase will take, because nothing knows.
 */
function PhaseElapsed({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(() => Date.now() - since);

  useEffect(() => {
    setElapsed(Date.now() - since);
    const timer = window.setInterval(() => setElapsed(Date.now() - since), 1000);
    return () => window.clearInterval(timer);
  }, [since]);

  const seconds = Math.max(0, Math.floor(elapsed / 1000));
  return seconds < 1 ? null : <small className="ask-run-elapsed">{seconds}s</small>;
}

type RunState = "working" | "stopped" | "failed";

const STATE_LABEL: Record<Exclude<RunState, "working">, string> = {
  stopped: "Stopped before it finished",
  failed: "Request interrupted",
};

/**
 * One status line, a segment per phase, and each finished phase with the one
 * fact it produced. Drawn from the same stream events as everything else, so a
 * stopped or failed run keeps exactly the progress it had made.
 */
export function RunProgress({
  run,
  presentedStage,
  state,
  stageStartedAt,
}: {
  run: RunData;
  presentedStage: AssistStage;
  state: RunState;
  stageStartedAt: number;
}) {
  const stages = stagesFor(run.path);
  const presentedIndex = Math.max(0, stages.findIndex((stage) => stage.id === presentedStage));
  const label = state === "working" ? stages[presentedIndex].running : STATE_LABEL[state];
  return (
    <section className="ask-run" data-state={state} aria-label="Progress">
      <div className="ask-run-status" role="status" aria-live="polite">
        <span className="ask-run-dot" aria-hidden="true" />
        <span className="ask-run-label">{label}</span>
        {state === "working" ? <PhaseElapsed since={stageStartedAt} /> : null}
      </div>
      <div className="ask-run-bar" aria-hidden="true">
        {stages.map((stage, index) => (
          <span
            key={stage.id}
            className={index < presentedIndex ? "is-done" : index === presentedIndex ? "is-current" : undefined}
          />
        ))}
      </div>
      <ol className="ask-run-steps">
        {stages.slice(0, presentedIndex).map((stage) => {
          const finding = phaseFinding(stage.id, run);
          return (
            <li key={stage.id}>
              <Check size={12} strokeWidth={2.6} aria-hidden="true" />
              <span>
                <strong>{stage.done}.</strong>
                {finding ? ` ${finding}` : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
