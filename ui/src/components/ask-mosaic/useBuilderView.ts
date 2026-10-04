import { useCallback, useState } from "react";

const STORAGE_KEY = "mosaic-ask-builder-view";

function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    // Storage can be blocked or absent; the view then simply starts off.
    return false;
  }
}

/**
 * Builder view: the run's recorded facts, steps and ranks, page-wide and off by
 * default. The choice is remembered per viewer when the browser allows it, and
 * works for the visit when it does not.
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
