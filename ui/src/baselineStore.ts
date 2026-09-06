/**
 * The pinned baseline's identity, kept where a page reload cannot take it.
 *
 * The Playground pins a "before" run so a repair can be measured against it,
 * and it held that pin in React state alone. `LabRail` tells the participant,
 * in as many words, that "reloading the page is the honest refresh, and it is
 * the one they already make after applying SQL" -- so the workflow the product
 * recommends is exactly the action that erased the evidence of the fault they
 * had just reproduced. The first run after the reload then became the new
 * baseline, and the comparison silently measured the repair against itself.
 *
 * Only the `search_event_id` is stored. The run itself is already durable in
 * `mosaic.search_event`, and `api.retrievalEventResponse` reads it back whole --
 * the same call the Shop hand-off uses. Storing the id and re-reading the server
 * copy keeps one authority for what a run contained; storing the response body
 * would create a second one that could drift from it.
 *
 * `sessionStorage`, not `localStorage`: the pin belongs to one sitting at one
 * machine. A workshop laptop is handed to the next attendee, and a baseline that
 * outlived the browser session would surface someone else's run as this
 * participant's "before".
 *
 * Every access is wrapped. A browser with site data disabled throws on the
 * property access itself, not on the read, and a Playground that cannot pin a
 * baseline must still run searches.
 */

const KEY = "mosaic.playground.baseline";

/** Mission id -> the `search_event_id` pinned for that mission. */
type PinnedBaselines = Record<string, string>;

function read(): PinnedBaselines {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    // Unreadable, malformed, or unavailable are one outcome here: nothing is
    // pinned. Reporting them apart would ask the participant to act on a
    // distinction none of their options depend on.
    return {};
  }
}

function write(value: PinnedBaselines): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    // A full or disabled store loses the pin across a reload, which is the
    // behaviour that existed before this module. It never blocks the run.
  }
}

/** The run pinned for this mission, or null when nothing is pinned for it. */
export function readPinnedBaseline(missionId: string): string | null {
  return read()[missionId] ?? null;
}

/**
 * Pin one run for one mission.
 *
 * Keyed per mission rather than as a single slot, because the missions are
 * independent scenarios: pinning Lab 2's baseline must not evict Lab 1's, and
 * returning to Lab 1 should find its own "before" still pinned.
 */
export function writePinnedBaseline(missionId: string, searchEventId: string): void {
  write({ ...read(), [missionId]: searchEventId });
}

/**
 * Drop this mission's pin.
 *
 * For the case where the baseline stops describing the request on screen -- an
 * edited query -- rather than for switching missions, which leaves the other
 * mission's pin exactly where it belongs.
 */
export function clearPinnedBaseline(missionId: string): void {
  const current = read();
  if (!(missionId in current)) return;
  delete current[missionId];
  write(current);
}
