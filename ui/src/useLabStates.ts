import { useEffect, useState } from "react";
import { api } from "./api";
import type { LabStateRecord } from "./types";

export interface LabStatesResult {
  /**
   * Null before the first read settles, and again once a new one has started.
   *
   * `LabRail` and `WorkshopProgress` both render this as "not checked" rather
   * than guessing a verdict, which is why a failed read (see `failed` below)
   * also clears it instead of leaving a stale value on screen.
   */
  labStates: LabStateRecord[] | null;
  /**
   * Whether the most recently settled read failed.
   *
   * Kept apart from `labStates` being null, which is also the ordinary state
   * while a request is in flight. A caller that needs to tell "still loading"
   * from "the read failed" -- rather than rendering both as "not checked" --
   * reads this.
   */
  failed: boolean;
}

/**
 * `GET /api/labs/state`, the one cheap, side-effect-free read every surface
 * that shows lab progress polls.
 *
 * Cheap and side-effect free on the service side too: it reads marker blocks
 * off disk and asks Aurora what two functions currently contain, spending no
 * retrieval. `LabRail` re-reads it after a new run or a completion proof, and
 * `WorkshopProgress` reads it once on mount; `refreshKey` is what tells the two
 * apart. Changing it starts a new read the same way a changed `missionId` used
 * to before this was shared -- callers that need both fold them into one key.
 *
 * The `active` flag, not a request-version counter, is what guards against a
 * StrictMode double-invoke or an unmount racing a slow read: this hook only
 * ever has one read in flight per key, so there is nothing for a second read
 * to race except its own effect's cleanup.
 */
export function useLabStates(refreshKey: string | number = ""): LabStatesResult {
  const [labStates, setLabStates] = useState<LabStateRecord[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .labsState()
      .then((value) => {
        if (!active) return;
        setLabStates(value.labs);
        setFailed(false);
      })
      .catch(() => {
        if (!active) return;
        setLabStates(null);
        setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  return { labStates, failed };
}
