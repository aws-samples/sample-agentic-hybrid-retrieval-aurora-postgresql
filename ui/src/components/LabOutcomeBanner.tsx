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
      <Icon size={22} aria-hidden="true" />
      <div>
        <span>{outcome.label}</span>
        <strong>{outcome.title}</strong>
        <p>{outcome.detail}</p>
      </div>
    </section>
  );
}
