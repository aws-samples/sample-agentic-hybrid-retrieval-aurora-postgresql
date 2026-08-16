import type { ReactNode } from "react";
import { LabsIntroFlow } from "./LabsIntroFlow";

type MosaicLabsMastheadProps = {
  title: string;
  deck: string;
  action?: ReactNode;
  supportingText?: string;
};

/**
 * Shared Labs masthead for the Explore and Studio observation views.
 */
export function MosaicLabsMasthead({
  title,
  deck,
  action,
  supportingText,
}: MosaicLabsMastheadProps) {
  return (
    <header className="labs-intro">
      <div className="labs-intro-copy">
        <h1>{title}</h1>
        <p className="labs-intro-deck">{deck}</p>
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
