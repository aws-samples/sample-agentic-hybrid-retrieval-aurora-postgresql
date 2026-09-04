import type { MosaicLabMission } from "./labMissions";
import { FORWARDABLE_FILTER_KEYS } from "./navigation";
import { armIndexName, requiredArms } from "./retrievalLanguage";
import type {
  AgentResponse,
  ProductSummary,
  ReadinessResponse,
  SearchFilters,
  SearchResponse,
} from "./types";

/**
 * `unhealthy` is not a fourth verdict on the participant's work.
 *
 * The three labs are taught as Broken -> Diagnose -> Fix -> Prove, so `broken`
 * has to keep meaning "the defect you were sent here to find". A missing index
 * or an unseeded corpus produces the same empty arm as an unrepaired CTE, and
 * reporting that as `broken` sends a participant to edit SQL that was never
 * the problem.
 */
export type LabOutcomeTone = "ready" | "broken" | "fixed" | "unhealthy";

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

/**
 * Whether the run that produced this response asked the scenario's own question.
 *
 * A scenario's assertions are about a request, not just a string: `typo-recovery`
 * expects the close-spelling arm to recover one product *inside* a domain, a price
 * ceiling and a stock gate. A run that carried the same words under different
 * gates retrieved a different pool, and grading it against the scenario would
 * report a repair that was never exercised, or a defect that was never present.
 *
 * Compared over `FORWARDABLE_FILTER_KEYS` rather than over every key, because
 * those are the only gates a link can carry between surfaces. `attributes` is a
 * map Shop cannot forward, so a run that omits it is not thereby a different
 * request, and comparing it would make every carried arrival read as a mismatch.
 */
export function runMatchesMissionGates(
  mission: MosaicLabMission,
  response: SearchResponse,
): boolean {
  const applied = response.applied_filters as Record<string, unknown>;
  const wanted = mission.filters as Record<string, unknown>;
  return FORWARDABLE_FILTER_KEYS.every(
    (key) => comparableGate(applied[key]) === comparableGate(wanted[key]),
  );
}

/**
 * One gate value, in the form both sides of that comparison can be read in.
 *
 * `SearchFilters.as_sql_json` drops false booleans before the service echoes a
 * filter set, because the SQL treats a missing key as unconstrained. So a
 * response can never carry `in_stock_only: false`, and comparing it against a
 * scenario that spells the false out would report a different request over a
 * gate neither side applied.
 */
function comparableGate(value: unknown): unknown {
  if (value === false || value === undefined) return null;
  return value;
}

/**
 * What is wrong with the environment, in the words the banner has to use, or
 * null when nothing readiness reports stands between the participant and the
 * checkpoint.
 *
 * A null readiness is not a fault. The read can fail for reasons that say
 * nothing about the cluster, and announcing an environment problem on the
 * strength of a failed status call is the same error in the other direction.
 */
function environmentFault(
  mission: MosaicLabMission,
  readiness: ReadinessResponse | null,
): string | null {
  if (!readiness) return null;
  const missingIndexes = readiness.database.missing_retrieval_indexes ?? [];
  const missingForThisLab = requiredArms(mission.expected_techniques)
    .map((arm) => armIndexName[arm])
    .filter((index) => missingIndexes.includes(index));
  if (missingForThisLab.length > 0) {
    return `Aurora is missing an index this scenario needs: ${
      missingForThisLab.join(", ")
    }. Re-apply the schema, then run this scenario again.`;
  }
  if (readiness.database_ready === false) {
    const missingFunctions = readiness.database.missing_retrieval_functions ?? [];
    const detail = missingIndexes.length || missingFunctions.length
      ? `Missing: ${[...missingIndexes, ...missingFunctions].join(", ")}.`
      : `The catalog reports ${
        readiness.database.product_count.toLocaleString("en-US")
      } products and ${
        readiness.database.embedded_product_count.toLocaleString("en-US")
      } embeddings.`;
    return `Aurora reports the workshop database is not ready. ${detail}`;
  }
  return null;
}

function unhealthyOutcome(detail: string): LabOutcome {
  return {
    tone: "unhealthy",
    label: "Environment blocked",
    title: "This is an environment problem, not the lab's fault",
    detail,
  };
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
  readiness: ReadinessResponse | null = null,
): LabOutcome {
  // Before anything the response says: an arm that never ran because its index
  // is gone produces exactly the evidence an unrepaired seam does.
  const fault = environmentFault(mission, readiness);
  if (fault) return unhealthyOutcome(fault);
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

/**
 * Which half of the scenario's request a run did not ask.
 *
 * The two halves send the participant somewhere different, so the neutral
 * verdict cannot report them with one sentence. Different words are an
 * experiment of the participant's own. The scenario's own words under other
 * gates is the checkpoint's question asked of a different pool, and telling
 * that participant their query is outside the checkpoint points at the one half
 * that had not diverged.
 */
export interface RunDivergence {
  /** Whether the run executed the scenario's own query. */
  queryMatches: boolean;
  /** Whether the run applied the scenario's own eligibility gates. */
  gatesMatch: boolean;
}

/**
 * The neutral verdict, for a run the selected scenario does not describe.
 *
 * `carried` separates the two ways that happens. A query typed into the
 * Playground is the participant's own experiment. A run handed over from Shop is
 * a real persisted run under Shop's gates, and saying "Live run complete" over it
 * hid where it came from while implying the participant had run something.
 *
 * `divergence` defaults to a differing query, which is the only case a caller
 * that cannot tell the two apart is entitled to claim.
 */
export function liveRetrievalOutcome(
  response: SearchResponse,
  carried = false,
  divergence: RunDivergence = { queryMatches: false, gatesMatch: false },
): LabOutcome {
  const resultCount = response.results.length;
  const title = `${resultCount} ranked ${resultCount === 1 ? "result" : "results"}`;
  if (carried) {
    return {
      tone: "ready",
      label: "Shop run loaded",
      title,
      detail:
        "These rows are the run Shop served, under the gates Shop applied. The lab verdict applies to the scenario's own filters, so run the scenario to check it.",
    };
  }
  const gatesDiverged = divergence.queryMatches && !divergence.gatesMatch;
  return {
    tone: "ready",
    label: "Live run complete",
    title,
    detail: gatesDiverged
      ? "This run used Shop's gates, so the lab verdict does not apply. Select the scenario and run it, or run the completion proof in Prove, to judge the repair against the scenario's own gates."
      : "This query is outside the selected checkpoint. Inspect its per-arm ranks and eligibility directly.",
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
