import missionManifest from "../../data/evals/mosaic_labs_missions.json";
import type { SearchFilters } from "./types";

export type MosaicLabStage = "recover" | "retrieve" | "rank" | "reason" | "optimize";
export type MosaicLabCheckpoint = "baseline" | "repair" | "comparison" | "advanced";

export interface MosaicLabMission {
  id: string;
  stage: MosaicLabStage;
  core: boolean;
  duration_minutes: number;
  title: string;
  query: string;
  filters: SearchFilters;
  target_product_ids: number[];
  expected_techniques: string[];
  checkpoint: MosaicLabCheckpoint;
  expected_outcome: string;
  assertions: string[];
  top_k: number;
}

interface MosaicLabManifest {
  version: number;
  name: string;
  session: {
    total_minutes: number;
    orientation_minutes: number;
    core_lab_minutes: number;
    scorecard_minutes: number;
  };
  corpus: {
    catalog_products: number;
    premium_visual_anchors: number;
    embedding_model_id: string;
    embedding_dimensions: number;
    candidate_generation: string[];
    fusion: string;
    reranker: string;
  };
  /** The three timed exercises, in run order. */
  missions: MosaicLabMission[];
  /** Retired exercises, kept in full so the eval harness and GAP ledger resolve. */
  self_paced: MosaicLabMission[];
}

export const mosaicLabManifest = missionManifest as MosaicLabManifest;
export const timedMosaicLabMissions = mosaicLabManifest.missions;
export const selfPacedMosaicLabMissions = mosaicLabManifest.self_paced;

/**
 * Every mission, timed first. The retrieval lab lets a participant inspect any
 * of them, so it reads this rather than the timed list alone.
 */
export const mosaicLabMissions = [...timedMosaicLabMissions, ...selfPacedMosaicLabMissions];

export function missionLabHref(mission: MosaicLabMission) {
  return `/labs/retrieval?mission=${encodeURIComponent(mission.id)}`;
}
