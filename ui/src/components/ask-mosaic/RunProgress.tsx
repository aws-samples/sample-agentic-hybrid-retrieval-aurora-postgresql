import { PulseDot } from "../PulseDot";
import type { RunData } from "./findings";
import { formatMilliseconds, toolChips, type ToolChip } from "./toolChips";
import { stagesFor, type AssistStage } from "./types";

const CHIP_STATE_WORD: Record<ToolChip["state"], string> = {
  done: "done",
  failed: "failed",
  denied: "declined",
};

function Chip({ chip }: { chip: ToolChip }) {
  return (
    <li className="ask-tool-chip" data-state={chip.state}>
      <i className="ask-tool-chip-dot" aria-hidden="true" />
      <span>{chip.label}</span>
      <span className="sr-only">, {CHIP_STATE_WORD[chip.state]}</span>
      {chip.latencyMs != null ? <small className="ask-tool-chip-ms">{formatMilliseconds(chip.latencyMs)}</small> : null}
    </li>
  );
}

type RunState = "working" | "stopped" | "failed" | "done";

const STATE_LABEL: Record<"stopped" | "failed", string> = {
  stopped: "Stopped before it finished",
  failed: "Request interrupted",
};

/**
 * One status line, a spinner and a label that changes in place as the service
 * announces each phase, and a chip for each tool the Retrieval agent has
 * called. Nothing ticks, so the live region only speaks when the phase changes. Once the answer starts, the chips stay above it
 * (`done`) and the status line goes. Drawn from the same stream events as everything
 * else, so a stopped or failed run keeps exactly the tools it had called.
 */
export function RunProgress({
  run,
  presentedStage,
  state,
}: {
  run: RunData;
  presentedStage: AssistStage;
  state: RunState;
}) {
  const stages = stagesFor(run.path);
  const current = stages.find((stage) => stage.id === presentedStage) ?? stages[0];
  const chips = toolChips(run.trace);
  if (state === "done" && !chips.length) return null;
  return (
    <section className="ask-run" data-state={state} aria-label={state === "done" ? "Tools used" : "Progress"}>
      {state === "done" ? null : (
        <p className="ask-run-status" role="status" aria-live="polite">
          {state === "working" ? (
            <PulseDot />
          ) : null}
          <span>{state === "working" ? current.running : STATE_LABEL[state]}</span>
        </p>
      )}
      {chips.length ? (
        <ul className="ask-tool-chips" aria-label="Tools the Retrieval agent called">
          {chips.map((chip) => <Chip key={chip.key} chip={chip} />)}
        </ul>
      ) : null}
    </section>
  );
}
