import { useCallback, useState } from "react";

const STORAGE_KEY = "mosaic-ask-builder-view";

function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    // Storage can be blocked or absent; the view then simply starts on.
    return true;
  }
}

/**
 * Builder view: the run's recorded facts, steps and ranks, page-wide and on by
 * default, so every answer shows the tool calls behind it. Turning it off is
 * remembered per viewer when the browser allows it, and works for the visit when
 * it does not.
 */
export function useBuilderView(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readStored);
  const update = useCallback((next: boolean) => {
    setOn(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
    } catch {
      // Not remembered; the switch still applies to this visit.
    }
  }, []);
  return [on, update];
}
