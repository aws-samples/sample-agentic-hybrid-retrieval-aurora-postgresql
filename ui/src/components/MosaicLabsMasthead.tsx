import type { ReactNode } from "react";

type MosaicLabsMastheadProps = {
  title: ReactNode;
  deck: string;
  action?: ReactNode;
  supportingText?: string;
};

/**
 * The masthead every Labs surface carries.
 *
 * Studio used to add a 194px decorative particle canvas here through a
 * `showFlow` flag. It carried no measurement, and it left the Studio masthead's
 * own rule 234px below the last line of copy, with only faint dots between them
 * and the next section's rule 40px further down: two hairlines bracketing an
 * empty band. Every other Labs surface goes copy, rule, gap, next section. One
 * masthead, one variant, and Studio now keeps that rhythm too.
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
    </header>
  );
}
