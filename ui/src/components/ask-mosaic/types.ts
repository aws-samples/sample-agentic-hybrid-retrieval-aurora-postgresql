import type { AgentPartial, AgentResponse } from "../../types";

/**
 * The single source for Ask Mosaic's own types.
 *
 * `AskMosaic.tsx` orchestrates the sidecar and owns `Turn`; `StageProgress`,
 * `EvidencePanels`, and `ResultCards` are presentational modules it composes.
 * Both directions need these types, so they live here instead of in either
 * side, which is what keeps the import graph one-way: presentation modules
 * import from `types.ts`, never from `AskMosaic.tsx` itself.
 */
export type AssistStage = "understand" | "retrieve" | "rank" | "answer";
export type AssistExecutionPath = "focused_follow_up" | "full_retrieval";

/**
 * One exchange: what was asked, and everything the service has streamed back
 * for it so far.
 *
 * The panel used to hold a single response, so every follow-up erased the
 * exchange that prompted it - "Compare top two" threw away the answer that
 * named the two products, and the panel snapped back to a spinner. Turns
 * accumulate instead, which is what makes the follow-ups worth pressing: the
 * comparison lands under the recommendation it came from.
 */
export interface AskMosaicTurn {
  id: number;
  question: string;
  /** Keeps a saved conversation from replacing results for a different Shop request. */
  contextKey?: string;
  response: AgentResponse | null;
  /** True only after the stream's terminal `complete` event has arrived. */
  completed: boolean;
  /**
   * Retrieval that has landed while the run is still going, so the stage that
   * is in progress has something real to show. Superseded by `response`.
   */
  partial: AgentPartial | null;
  /** Text delivered so far by `answer_delta`. Empty until the first token. */
  streamed: string;
  stage: AssistStage | null;
  /**
   * `Date.now()` at the moment `stage` last changed, so the step that is working
   * can report how long it has been working.
   *
   * Synthesis is the long pole: the answer cannot be shown until it has been
   * checked against the citations it claims, so the last step sits at "in
   * progress" for as long as that model call takes. With nothing counting, a
   * measured fourteen seconds read as a hung panel.
   */
  stageStartedAt: number;
  executionPath: AssistExecutionPath;
  stageDetail: string;
  error: string;
  /**
   * True once a reader presses Stop, or a follow-up filter change replaces
   * this turn before it finished. A normal terminal state, not a failure:
   * whatever text, shortlist, and trace had already arrived stay visible.
   */
  cancelled: boolean;
  loading: boolean;
}

/** One stage of the progress rail, in the order it presents. */
export interface AssistStageConfig {
  id: AssistStage;
  label: string;
  title: string;
  description: string;
}

export const fullRetrievalStages: AssistStageConfig[] = [
  {
    id: "understand",
    label: "Request",
    title: "Search criteria",
    description: "Identifying requirements and catalog filters from your request.",
  },
  {
    id: "retrieve",
    label: "Retrieval",
    title: "Product shortlist",
    description: "Finding relevant products within your search criteria.",
  },
  {
    id: "rank",
    label: "Comparison",
    title: "Product comparison",
    description: "Comparing features and trade-offs using catalog records.",
  },
  {
    id: "answer",
    label: "Sources",
    title: "Supporting evidence",
    description: "Linking recommendations to their source records.",
  },
];

export const focusedFollowUpStages: AssistStageConfig[] = [
  {
    id: "understand",
    label: "Request",
    title: "Follow-up context",
    description: "Interpreting your follow-up in the context of the current shortlist.",
  },
  {
    id: "rank",
    label: "Comparison",
    title: "Product comparison",
    description: "Reviewing the product records relevant to your follow-up.",
  },
  {
    id: "answer",
    label: "Sources",
    title: "Supporting evidence",
    description: "Checking the new answer against freshly retrieved evidence.",
  },
];
