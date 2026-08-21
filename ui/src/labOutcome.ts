import type { MosaicLabMission } from "./labMissions";
import type {
  AgentResponse,
  ProductSummary,
  SearchFilters,
  SearchResponse,
} from "./types";

export type LabOutcomeTone = "ready" | "broken" | "fixed";

export interface LabOutcome {
  tone: LabOutcomeTone;
  label: string;
  title: string;
  detail: string;
}

function matchesFilters(product: ProductSummary, filters: SearchFilters) {
  return (
    (!filters.domain || product.domain === filters.domain)
    && (
      filters.max_price_cents === undefined
      || product.price_cents <= filters.max_price_cents
    )
    && (
      !filters.in_stock_only
      || product.availability === "in_stock"
      || product.availability === "low_stock"
    )
    && Object.entries(filters.attributes ?? {}).every(
      ([key, value]) => product.attributes[key] === value,
    )
  );
}

function rrfIsCorrect(product: ProductSummary, rrfK: number) {
  if (!product.signals) return false;
  let expected = 0;
  let contributed = false;
  for (const arm of ["fts", "trigram", "semantic"] as const) {
    const signal = product.signals[arm];
    if (signal.rank === null) continue;
    const contribution = 1 / (rrfK + signal.rank);
    if (
      signal.rrf_contribution === null
      || Math.abs(signal.rrf_contribution - contribution) > 1e-9
    ) {
      return false;
    }
    expected += contribution;
    contributed = true;
  }
  return contributed && Math.abs(product.signals.rrf_score - expected) <= 1e-9;
}

function readyOutcome(mission: MosaicLabMission): LabOutcome {
  return {
    tone: "ready",
    label: "Ready to run",
    title: mission.discover_label,
    detail: "Run this scenario against Aurora to inspect the measured result.",
  };
}

function participantCopy(
  mission: MosaicLabMission,
  fixed: boolean,
): Pick<LabOutcome, "label" | "title" | "detail"> {
  if (mission.stage === "retrieve") {
    return fixed
      ? {
          label: "Repair verified",
          title: "Fuzzy retrieval is contributing",
          detail:
            "The target carries a pg_trgm rank and RRF contribution, and every result remains eligible.",
        }
      : {
          label: "Issue reproduced",
          title: "Fuzzy retrieval is still disconnected",
          detail:
            "The request completed, but the target has no trigram contribution in the fused pool.",
        };
  }
  if (mission.stage === "rank") {
    return fixed
      ? {
          label: "Repair verified",
          title: "Fusion now respects source rank",
          detail:
            "Per-arm contributions follow 1 / (k + rank), and the expected product leads before reranking.",
        }
      : {
          label: "Issue reproduced",
          title: "Fusion is flattening per-arm rank",
          detail:
            "The final order looks plausible, but the fused order does not preserve each arm's rank.",
        };
  }
  if (mission.stage === "reason") {
    return fixed
      ? {
          label: "Grounding verified",
          title: "Every citation resolves to retrieved evidence",
          detail:
            "The answer of record is bounded to retrieved products and product-owned evidence.",
        }
      : {
          label: "Grounding blocked",
          title: "Synthesis cannot authorize its evidence",
          detail:
            "Retrieval completed, but the application correctly refused an unsupported answer.",
        };
  }
  return {
    label: fixed ? "Check passed" : "Review needed",
    title: mission.discover_label,
    detail: fixed
      ? "The measured response satisfies this checkpoint."
      : "The measured response does not yet satisfy this checkpoint.",
  };
}

function participantOutcome(
  mission: MosaicLabMission,
  fixed: boolean,
): LabOutcome {
  return {
    tone: fixed ? "fixed" : "broken",
    ...participantCopy(mission, fixed),
  };
}

export function retrievalLabOutcome(
  mission: MosaicLabMission,
  response: SearchResponse | null,
): LabOutcome {
  if (!response) return readyOutcome(mission);

  const targets = response.results.filter((product) =>
    mission.target_product_ids.includes(product.product_id));
  const targetsPresent = targets.length === mission.target_product_ids.length;
  const eligible = response.results.every((product) =>
    matchesFilters(product, mission.filters));

  if (mission.participant_edit && mission.stage === "retrieve") {
    const targetRecovered = targets.some(
      (product) =>
        product.signals?.trigram.rank != null
        && product.signals?.trigram.rrf_contribution != null,
    );
    const trigramPool =
      response.diagnostics?.candidate_counts.trigram_in_pool ?? 0;
    return participantOutcome(
      mission,
      targetsPresent && targetRecovered && trigramPool > 0 && eligible,
    );
  }

  if (mission.participant_edit && mission.stage === "rank") {
    const rrfK = response.diagnostics?.retrieval_profile.rrf_k;
    const arithmeticCorrect = (
      typeof rrfK === "number"
      && response.results.length > 0
      && response.results.every((product) => rrfIsCorrect(product, rrfK))
    );
    const canonicalOrderCorrect = targets.every(
      (product) =>
        product.signals?.pre_rerank_rank === 1
        && product.signals.final_rank === 1,
    );
    return participantOutcome(
      mission,
      targetsPresent && arithmeticCorrect && canonicalOrderCorrect && eligible,
    );
  }

  const observed = targetsPresent && eligible;
  return {
    tone: observed ? "fixed" : "broken",
    label: observed ? "Check passed" : "Review needed",
    title: observed ? "Expected targets are present" : "Expected targets are missing",
    detail: observed
      ? "Inspect the visible provenance before accepting the checkpoint."
      : "The current response does not contain every expected eligible target.",
  };
}

export function liveRetrievalOutcome(response: SearchResponse): LabOutcome {
  const resultCount = response.results.length;
  return {
    tone: "ready",
    label: "Live run complete",
    title: `${resultCount} ranked ${resultCount === 1 ? "result" : "results"}`,
    detail:
      "This query is outside the selected checkpoint. Inspect its per-arm ranks and eligibility directly.",
  };
}

function successfulTool(agent: AgentResponse, tool: string) {
  return agent.trace.some(
    (step) => step.tool === tool && step.outcome === "success",
  );
}

export function agentLabOutcome(
  mission: MosaicLabMission,
  agent: AgentResponse | null,
  error: string,
): LabOutcome {
  if (!agent && !error) return readyOutcome(mission);
  if (!agent && mission.participant_edit) return participantOutcome(mission, false);

  const recommendationIds = new Set(
    (agent?.recommendations ?? []).map((product) => product.product_id),
  );
  const citations = agent?.citations ?? [];
  const citedProductIds = new Set(
    citations.map((citation) => citation.product_id),
  );
  const grounded = (
    (agent?.recommendations.length ?? 0) >= 2
    && citations.length > 0
    && [...recommendationIds].every((productId) => citedProductIds.has(productId))
    && citations.every(
      (citation) =>
        citation.evidence_id > 0
        && recommendationIds.has(citation.product_id),
    )
    && successfulTool(agent!, "search_products")
    && successfulTool(agent!, "compare_products")
    && successfulTool(agent!, "get_product_evidence")
  );

  if (mission.participant_edit) return participantOutcome(mission, grounded);

  return {
    tone: grounded ? "fixed" : "broken",
    label: grounded ? "Grounding verified" : "Grounding blocked",
    title: grounded
      ? "Every citation resolves to retrieved evidence"
      : "The answer is missing required grounding",
    detail: grounded
      ? "Tool receipts and evidence-backed citations are visible below."
      : "The current answer does not expose the required grounding evidence.",
  };
}
