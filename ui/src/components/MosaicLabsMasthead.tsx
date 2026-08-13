import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { LabsIntroFlow } from "./LabsIntroFlow";

type MosaicLabsMastheadProps = {
  eyebrow: string;
  title: string;
  deck: string;
  currentView: string;
  action?: ReactNode;
  supportingText?: string;
};

/**
 * Shared Labs masthead. Explore and Studio are two observation views of the
 * same product surface, so their visual entry point must remain identical.
 */
export function MosaicLabsMasthead({
  eyebrow,
  title,
  deck,
  currentView,
  action,
  supportingText,
}: MosaicLabsMastheadProps) {
  return (
    <header className="labs-intro">
      <div className="labs-intro-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="labs-intro-deck">{deck}</p>
        <div className="labs-intro-path" aria-label="Participant workflow">
          <span>Code Editor</span>
          <ArrowRight size={15} aria-hidden="true" />
          <span>Shop</span>
          <ArrowRight size={15} aria-hidden="true" />
          <strong>{currentView}</strong>
        </div>
        {action || supportingText ? (
          <div className="labs-intro-actions">
            {action}
            {supportingText ? <span>{supportingText}</span> : null}
          </div>
        ) : null}
      </div>
      <div className="labs-intro-flow-wrap">
        <LabsIntroFlow />
      </div>
    </header>
  );
}
