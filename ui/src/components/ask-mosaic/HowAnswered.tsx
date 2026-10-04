import { Check, ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import { phaseFinding, runSummary, type RunData } from "./findings";
import { stagesFor } from "./types";

/**
 * The run in one collapsed line: how many phases, searches and sources, and how
 * long it took. Opening it lists what each phase found.
 */
export function HowAnswered({ run, durationMs }: { run: RunData; durationMs?: number }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="ask-fold">
      <button
        type="button"
        className="ask-fold-toggle"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <Check size={13} strokeWidth={2.6} aria-hidden="true" />
        <strong>How Mosaic answered</strong>
        <span>{runSummary(run, durationMs)}</span>
        <ChevronDown size={14} aria-hidden="true" className="ask-fold-chevron" />
      </button>
      {open ? (
        <ul id={panelId} className="ask-fold-findings">
          {stagesFor(run.path).map((stage) => {
            const finding = phaseFinding(stage.id, run);
            return (
              <li key={stage.id}>
                <strong>{stage.done}.</strong>
                {finding ? ` ${finding}` : ""}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
