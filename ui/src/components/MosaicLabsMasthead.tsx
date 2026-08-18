import type { ReactNode } from "react";
import { LabsIntroFlow } from "./LabsIntroFlow";

type MosaicLabsMastheadProps = {
  title: ReactNode;
  deck: string;
  action?: ReactNode;
  supportingText?: string;
  showFlow?: boolean;
};

/**
 * Shared Labs masthead with an optional Studio-only particle field.
 */
export function MosaicLabsMasthead({
  title,
  deck,
  action,
  supportingText,
  showFlow = false,
}: MosaicLabsMastheadProps) {
  return (
    <header className={`labs-intro labs-intro--${showFlow ? "animated" : "compact"}`}>
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
      {showFlow ? (
        <div className="labs-intro-flow-wrap">
          <LabsIntroFlow />
        </div>
      ) : null}
    </header>
  );
}
