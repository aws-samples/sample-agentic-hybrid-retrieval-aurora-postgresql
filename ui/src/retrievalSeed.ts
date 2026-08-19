import seed from "./data/retrievalSeedRun.json";
import type { SearchResponse } from "./types";

/**
 * The Retrieval Observatory's first paint: one real Aurora run, committed.
 *
 * The surface has to be populated before a participant presses anything, and the
 * honest way to do that is a capture rather than a drawing. `Run pipeline`
 * replaces this with a fresh response and the provenance badge follows.
 *
 * Written by `scripts/capture_retrieval_seed.py`, never by hand.
 * `retrievalSeed.test.ts` re-derives the fusion arithmetic from this file, which
 * an invented response cannot satisfy.
 */
export interface SeedProvenance {
  captured_at: string;
  mission_id: string;
  producer: string;
  search_event_id: string;
  note: string;
}

export const seedProvenance: SeedProvenance = seed.provenance;

// A JSON import widens every union member to `string`, so the structural type does
// not survive the import even though the values are correct. The runtime shape is
// asserted in retrievalSeed.test.ts rather than trusted.
export const seedRun = seed.response as unknown as SearchResponse;

/**
 * The captured run, but only under the scenario it was captured for.
 *
 * One scenario's ranks presented as another's illustration is the failure the
 * fixture replay committed. Both the surface and its outcome banner read the rule
 * from here so they cannot disagree about which run is on screen.
 *
 * Args:
 *   exampleId: The scenario currently selected, if any.
 *
 * Returns:
 *   The captured response, or null when it does not describe this scenario.
 */
export function seedRunFor(exampleId: string | undefined): SearchResponse | null {
  return exampleId === seedProvenance.mission_id ? seedRun : null;
}
