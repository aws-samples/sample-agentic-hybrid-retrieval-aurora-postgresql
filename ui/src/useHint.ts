import { createContext, useCallback, useContext, useState } from "react";
import { hasSeenTour } from "./tour";

/**
 * Whether tips may open. Shell sets it from the same flag as the tours' first-visit
 * start, so tests and automated screen captures see no tip they did not ask for.
 */
export const HintsContext = createContext(false);

/** One tip: `show` opens it unless this browser has seen it or another spotlight is up. */
export function useHint(key: string) {
  const enabled = useContext(HintsContext);
  const [open, setOpen] = useState(false);
  const show = useCallback(() => {
    if (!enabled || hasSeenTour(key) || document.querySelector(".spotlight-tour")) return;
    setOpen(true);
  }, [enabled, key]);
  const close = useCallback(() => setOpen(false), []);
  return { open, show, close };
}
