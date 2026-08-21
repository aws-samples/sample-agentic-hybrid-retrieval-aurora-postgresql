import { CircleAlert, CircleCheck, FlaskConical } from "lucide-react";
import type { LabOutcome } from "../labOutcome";

const icons = {
  ready: FlaskConical,
  broken: CircleAlert,
  fixed: CircleCheck,
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
