import { CircleAlert, CircleCheck, FlaskConical, ServerCrash } from "lucide-react";
import type { LabOutcome } from "../labOutcome";

/**
 * A distinct mark for `unhealthy`, not a second use of the broken one.
 *
 * The two states look identical in the response and mean opposite things about
 * what the participant should do next, so the banner cannot draw them the same.
 */
const icons = {
  ready: FlaskConical,
  broken: CircleAlert,
  fixed: CircleCheck,
  unhealthy: ServerCrash,
};

export function LabOutcomeBanner({ outcome }: { outcome: LabOutcome }) {
  const Icon = icons[outcome.tone];
  return (
    <section
      className={`lab-outcome ${outcome.tone}`}
      aria-live="polite"
      aria-label="Workshop experiment state"
    >
      <div className="lab-outcome-status">
        <span className="lab-outcome-icon">
          <Icon size={18} aria-hidden="true" />
        </span>
        <span>{outcome.label}</span>
      </div>
      <div className="lab-outcome-copy">
        <strong>{outcome.title}</strong>
        <p>{outcome.detail}</p>
      </div>
    </section>
  );
}
