import seed from "./data/retrievalSeedRun.json";
import type { SearchResponse } from "./types";

/**
 * A committed Aurora capture for deterministic matrix and arithmetic tests.
 *
 * The participant surface deliberately starts empty and accepts only a live run.
 * Written by `scripts/capture_retrieval_seed.py`, never by hand.
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
