import missionManifest from "../../data/evals/mosaic_labs_missions.json";
import type { SearchFilters } from "./types";

export type MosaicLabStage = "retrieve" | "rank" | "reason" | "optimize";
export type MosaicLabCheckpoint = "baseline" | "repair" | "advanced";
export type MosaicLabPlacement = "lab-1" | "lab-2" | "lab-3" | "advanced-labs";

export interface MosaicParticipantEdit {
  file: string;
  approximate_lines: number;
  task: string;
  broken_state: string;
  fixed_state: string;
  observe_before: string[];
  observe_after: string[];
  checkpoint_question: string;
}

export interface MosaicCitationSupport {
  product_id: number;
  evidence_type: string;
  all_terms: string[];
}

export interface MosaicLabMission {
  id: string;
  stage: MosaicLabStage;
  core: boolean;
  placement?: MosaicLabPlacement;
  duration_minutes: number;
  title: string;
  /**
   * Compact participant-facing label used by the Playground scenario picker,
   * the rank table's empty-state hint, and the lab outcome copy.
   *
   * Discover intentionally does not print it.
   */
  discover_label: string;
  canonical_query_id?: string;
  query: string;
  filters: SearchFilters;
  target_product_ids: number[];
  expected_techniques: string[];
  checkpoint: MosaicLabCheckpoint;
  participant_edit?: MosaicParticipantEdit;
  expected_outcome: string;
  assertions: string[];
  required_citation_support?: MosaicCitationSupport[];
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
    contingency_minutes: number;
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

/** Workshop reading order: Retrieve, then Rank, then Reason, then the extras. */
const STAGE_ORDER: MosaicLabStage[] = ["retrieve", "rank", "reason", "optimize"];

export const stageLabels: Record<MosaicLabStage, string> = {
  retrieve: "Retrieve",
  rank: "Rank",
  reason: "Reason",
  optimize: "Advanced",
};

/**
 * The scenarios grouped the way the session runs, for a picker.
 *
 * The flat list is manifest order: the three core labs, then the supporting
 * checks. That interleaves stages, so a picker built straight from it reads
 * retrieve, rank, reason, retrieve, retrieve, retrieve, rank, rank, reason,
 * optimize, and the canonical query ids jump 003, 008, 010, 001, 004, 013.
 * Grouping by stage and sorting by canonical id inside each group gives one
 * reading order without renaming anything: those ids are bound by
 * scripts/mission_contract.py to a graded query in
 * data/evals/canonical_queries.jsonl, so they are not ours to renumber.
 */
export function retrievalExamplesByStage(): Array<{
  stage: MosaicLabStage;
  label: string;
  examples: MosaicLabMission[];
}> {
  return STAGE_ORDER.map((stage) => ({
    stage,
    label: stageLabels[stage],
    examples: mosaicRetrievalExamples
      .filter((example) => example.stage === stage)
      .sort((left, right) =>
        (left.canonical_query_id ?? "G-999").localeCompare(right.canonical_query_id ?? "G-999"),
      ),
  })).filter((group) => group.examples.length > 0);
}

export function retrievalExampleHref(example: MosaicLabMission) {
  if (example.stage === "reason") {
    const params = new URLSearchParams({
      ask: "1",
      mission: example.id,
      q: example.query,
    });
    Object.entries(example.filters).forEach(([key, value]) => {
      if (
        value !== undefined
        && value !== null
        && (
          typeof value === "string"
          || typeof value === "number"
          || typeof value === "boolean"
        )
      ) {
        params.set(key, String(value));
      }
    });
    return `/catalog?${params.toString()}`;
  }
  return `/labs/retrieval?example=${encodeURIComponent(example.id)}`;
}
