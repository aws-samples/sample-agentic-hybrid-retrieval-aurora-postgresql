import { Check, ChevronDown, Info } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { phaseFinding, runSummary, type RunData } from "./findings";
import { stagesFor } from "./types";

/**
 * How the tools work, after the answer: the run in one collapsed line (how many
 * steps, searches and sources, and how long it took), and what each phase found
 * once it is open. Builder view passes the recorded calls as `children`, which
 * replace that list (they carry the same phases with each call's arguments and
 * timing), and opens the disclosure with the switch.
 *
 * A declined run gets a neutral icon: the Retrieval agent finished its work,
 * but nothing here says it found a recommendation.
 */
export function HowAnswered({
  run,
  durationMs,
  declined,
  builder,
  children,
}: {
  run: RunData;
  durationMs?: number;
  declined: boolean;
  builder: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(builder);
  const panelId = useId();
  useEffect(() => { setOpen(builder); }, [builder]);
  const Icon = declined ? Info : Check;
  return (
    <div className="ask-fold" data-declined={declined ? "" : undefined}>
      <button
        type="button"
        className="ask-fold-toggle"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon size={13} strokeWidth={2.6} aria-hidden="true" />
        <strong>How the tools work</strong>
        <span>{runSummary(run, durationMs)}</span>
        <ChevronDown size={14} aria-hidden="true" className="ask-fold-chevron" />
      </button>
      {open ? (
        <div id={panelId} className="ask-fold-panel">
          {children ?? (
          <ul className="ask-fold-findings">
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
          )}
        </div>
      ) : null}
    </div>
  );
}
