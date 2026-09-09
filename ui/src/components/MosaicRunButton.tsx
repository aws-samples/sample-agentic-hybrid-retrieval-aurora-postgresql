import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import "../mosaic-run-button.css";

/** Keep a live request's action and status in the same, stable space. */
export function MosaicRunButton({ running = false, stage, children, className = "", disabled, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { running?: boolean; stage?: number }) {
  return <button {...props} className={`mosaic-run-button ${className}`} disabled={disabled || running} aria-busy={running}>
    {running && <LoaderCircle size={18} className="mosaic-run-spinner" aria-hidden="true" />}
    <span>{children}</span>
    {running && stage != null && <span className="mosaic-run-steps" aria-hidden="true">{[0, 1, 2].map((index) => <span key={index} data-reached={index <= stage} />)}</span>}
  </button>;
}
