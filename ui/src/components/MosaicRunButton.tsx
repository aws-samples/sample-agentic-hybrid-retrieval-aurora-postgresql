import { LoaderCircle, Send } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import "../mosaic-run-button.css";

type MosaicRunButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** The action's name: its accessible name and tooltip, and its visible text when `showLabel` is set. */
  label: string;
  /** Print the label beside the plane. Only where the plane alone would not say what is being sent. */
  showLabel?: boolean;
  running?: boolean;
};

/**
 * The paper plane that sends a request to Mosaic.
 *
 * It is the disc Discover and Shop submit a search with, so every surface
 * starts a run the same way. A request in flight swaps the plane for a
 * spinner and keeps the button busy until the run reports back.
 */
export function MosaicRunButton({ label, showLabel = false, running = false, className = "", disabled, ...props }: MosaicRunButtonProps) {
  return <button
    {...props}
    className={`mosaic-run-button${showLabel ? " labelled" : ""}${className ? ` ${className}` : ""}`}
    disabled={disabled || running}
    aria-busy={running}
    aria-label={showLabel ? undefined : label}
    title={showLabel ? undefined : label}
  >
    {showLabel ? <span className="mosaic-run-label">{label}</span> : null}
    <span className="mosaic-run-disc" aria-hidden="true">
      {running ? <LoaderCircle size={18} className="mosaic-run-spinner" /> : <Send size={16} />}
    </span>
  </button>;
}
