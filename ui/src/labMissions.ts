import missionManifest from "../../data/evals/mosaic_labs_missions.json";
import type { SearchFilters } from "./types";

export type MosaicLabStage = "retrieve" | "rank" | "reason" | "optimize";
export type MosaicLabCheckpoint = "baseline" | "repair" | "comparison" | "advanced";
export type MosaicLabPlacement = "lab-1" | "advanced-labs";

export interface MosaicLabMission {
  id: string;
  stage: MosaicLabStage;
  core: boolean;
  placement?: MosaicLabPlacement;
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
  /** The three required labs, in run order. */
  missions: MosaicLabMission[];
  /** Required checkpoints and optional advanced checks backed by the same evaluator. */
  supporting_checks: MosaicLabMission[];
}

export const mosaicLabManifest = missionManifest as MosaicLabManifest;
export const coreMosaicLabs = mosaicLabManifest.missions;
export const supportingMosaicChecks = mosaicLabManifest.supporting_checks;

/**
 * Every validated retrieval example, with the required labs first. The
 * inspection surface can replay both lab anchors and their supporting checks.
 */
export const mosaicRetrievalExamples = [...coreMosaicLabs, ...supportingMosaicChecks];

export function retrievalExampleHref(example: MosaicLabMission) {
  return `/labs/retrieval?example=${encodeURIComponent(example.id)}`;
}
