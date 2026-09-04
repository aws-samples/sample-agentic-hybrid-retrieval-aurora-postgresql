"""The participant-visible acceptance checks for the three labs, defined once.

Two transports evaluate the same conditions over the same evidence:
`scripts/validate_lab.py`, which fetches it over HTTP from a running API, and
`service/lab_proof.py`, which runs the production search path in-process and
reads persisted Aurora receipts. Neither owns the logic. The CLI held the only
copy until the completion-proof endpoint needed the same claims, and two
implementations of one claim is how a lab comes to report PASS on the terminal
and FAIL in the browser.

Every check carries its falsifier, for the reason `service/assertions.py`
states: a check whose failure condition cannot occur reads as evidence while
proving nothing. `LabCheck` refuses to be constructed without one.

Nothing here opens a connection or issues a request. Every function takes
already-loaded responses and rows, which is what lets both transports be tested
against the same vocabulary, and what keeps this module from becoming a third
retrieval implementation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from service.retrieval_fingerprint import explain

REPO = Path(__file__).resolve().parents[1]
MISSION_CONTRACT = REPO / "data" / "evals" / "mosaic_labs_missions.json"

#: Which mission stage each lab is graded against. The labs are numbered for
#: participants; the contract is keyed by the Retrieve -> Rank -> Reason stage.
LAB_STAGES: dict[int, str] = {1: "retrieve", 2: "rank", 3: "reason"}

#: Floating-point slack for one reciprocal-rank contribution. Not a retrieval
#: tunable: it is the comparison tolerance for a value the SQL already computed.
CONTRIBUTION_TOLERANCE = 1e-9


@dataclass(frozen=True)
class LabCheck:
    """One acceptance condition, its verdict, and what would falsify it.

    Attributes:
        name: The participant-facing label, stable across transports.
        passed: Whether the condition held on the evidence supplied.
        falsifier: The concrete condition under which this check fails. Stated
            independently of this particular run, so the claim can be argued
            with rather than taken on faith.
        detail: What was actually found, in the house error style when the
            check failed: the offending value, then the nearest fix.
    """

    name: str
    passed: bool
    falsifier: str
    detail: str

    def __post_init__(self) -> None:
        if not self.falsifier.strip():
            raise ValueError(
                f"check {self.name!r} has no falsifier; a check that cannot "
                "state its own failure condition must not be admitted"
            )


@dataclass(frozen=True)
class RetrievalReceipt:
    """One persisted retrieval run, reduced to what the Lab 3 checks read."""

    search_event_id: str
    query: str
    candidate_product_ids: frozenset[int]


@dataclass(frozen=True)
class AgentEvidence:
    """Everything the Lab 3 HTTP checks need that is not in the agent response.

    The transport fetches it; the checks never do. `captured_plan` and
    `replayed_plan` are `None` when the mission does not require an EXPLAIN
    plan, or when no explained retrieval receipt exists to capture one for.
    """

    receipts: tuple[RetrievalReceipt, ...] = ()
    resolved_evidence: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    captured_plan: Any = None
    replayed_plan: Any = None


@dataclass(frozen=True)
class PersistedAgentRun:
    """One completed agent turn as Aurora recorded it, and nothing more.

    The completion proof spends no agent turn, so every Lab 3 fact it grades
    has to come off `mosaic.agent_turn`, `mosaic.agent_tool_event`, and the
    `mosaic.search_event` rows linked to that turn.
    """

    agent_run_id: str
    assistant_message: str | None
    selected_products: tuple[int, ...]
    synthesis_outcome: str | None
    citations: tuple[Mapping[str, Any], ...]
    resolved_evidence: Mapping[int, Mapping[str, Any]]
    evidence_events: tuple[Mapping[str, Any], ...]
    search_filters: tuple[Mapping[str, Any], ...]


def load_mission(stage: str) -> dict[str, Any]:
    """The core mission for one Retrieve -> Rank -> Reason stage."""
    contract = json.loads(MISSION_CONTRACT.read_text(encoding="utf-8"))
    return next(item for item in contract["missions"] if item["stage"] == stage)


def load_case(case_id: str) -> dict[str, Any]:
    """One mission or supporting check, by its contract id."""
    contract = json.loads(MISSION_CONTRACT.read_text(encoding="utf-8"))
    cases = contract["missions"] + contract["supporting_checks"]
    return next(item for item in cases if item["id"] == case_id)


def mission_for_lab(lab_id: int) -> dict[str, Any]:
    """The mission a lab is graded against."""
    return load_mission(LAB_STAGES[lab_id])


def eligible(result: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    """Whether one returned product satisfies the mission's hard filters."""
    availability = result.get("availability")
    return (
        (not filters.get("domain") or result.get("domain") == filters["domain"])
        and (
            filters.get("max_price_cents") is None
            or result.get("price_cents", 0) <= filters["max_price_cents"]
        )
        and (
            not filters.get("in_stock_only")
            or availability in {"in_stock", "low_stock"}
        )
        and all(
            (result.get("attributes") or {}).get(key) == value
            for key, value in (filters.get("attributes") or {}).items()
        )
    )


def _price_preserved(required: Mapping[str, Any], applied: Mapping[str, Any]) -> bool:
    if required.get("max_price_cents") is not None and (
        applied.get("max_price_cents") is None
        or applied["max_price_cents"] > required["max_price_cents"]
    ):
        return False
    return not (
        required.get("min_price_cents") is not None
        and (
            applied.get("min_price_cents") is None
            or applied["min_price_cents"] < required["min_price_cents"]
        )
    )


def _identity_preserved(
    required: Mapping[str, Any],
    applied: Mapping[str, Any],
) -> bool:
    if required.get("domain") and applied.get("domain") != required["domain"]:
        return False
    if required.get("category_key") and (
        applied.get("category_key") != required["category_key"]
    ):
        return False
    if required.get("brand") and (
        str(applied.get("brand") or "").casefold() != str(required["brand"]).casefold()
    ):
        return False
    return not (
        required.get("availability")
        and applied.get("availability") != required["availability"]
    )


def constraints_preserved(
    required: Mapping[str, Any],
    applied: Mapping[str, Any],
) -> bool:
    """Whether an agent-issued search kept the structured envelope it was given.

    Narrowing is allowed and widening is not: a declared ceiling may be lowered,
    never raised, and a declared identity may not be swapped for another.
    """
    if not _identity_preserved(required, applied):
        return False
    if not _price_preserved(required, applied):
        return False
    if required.get("in_stock_only") and applied.get("in_stock_only") is not True:
        return False
    if required.get("min_rating") is not None and (
        applied.get("min_rating") is None
        or applied["min_rating"] < required["min_rating"]
    ):
        return False
    return all(
        (applied.get("attributes") or {}).get(key) == value
        for key, value in (required.get("attributes") or {}).items()
    )


def _results(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(response.get("results") or [])


def _target(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    wanted = set(mission.get("target_product_ids") or [])
    return next((item for item in results if item["product_id"] in wanted), None)


def _signals(result: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return (result or {}).get("signals") or {}


def _arm(signals: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return signals.get(name) or {}


# ---------------------------------------------------------------------------
# Lab 1 -- build hybrid retrieval
# ---------------------------------------------------------------------------


def _lab_1_anchor(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> LabCheck:
    target = _target(mission, results)
    wanted = sorted(mission.get("target_product_ids") or [])
    return LabCheck(
        name="expected retrieval anchor present",
        passed=target is not None,
        falsifier=(
            "the mission's target product reaches no candidate arm. With the "
            "pg_trgm channel disconnected, an all-misspelled query produces no "
            "lexical match and ranks the target outside the vector arm's "
            "budget, so it is absent from the window entirely."
        ),
        detail=(
            f"product {target['product_id']} is in the returned window"
            if target is not None
            else explain(
                f"no result among {len(results)} carrying product id(s) {wanted}",
                "restore the trigram CTE and its candidate channel in "
                "mosaic_search.search_hybrid_rrf, then re-apply the function",
            )
        ),
    )


def _lab_1_provenance(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> LabCheck:
    signals = _signals(_target(mission, results))
    trigram = _arm(signals, "trigram")
    rank = trigram.get("rank")
    contribution = trigram.get("rrf_contribution")
    return LabCheck(
        name="trigram provenance present",
        passed=rank is not None and contribution is not None,
        falsifier=(
            "the target is returned without a pg_trgm rank or without its RRF "
            "contribution, which means it arrived through another arm and the "
            "trigram repair is unproven by this result."
        ),
        detail=(
            f"trigram rank {rank} contributing {contribution}"
            if rank is not None and contribution is not None
            else explain(
                f"signals.trigram rank={rank!r} rrf_contribution={contribution!r}",
                "restore the trigram candidate channel so the fused row carries "
                "its source rank and reciprocal-rank contribution",
            )
        ),
    )


def _lab_1_filters(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> LabCheck:
    filters = mission.get("filters") or {}
    violations = [item["product_id"] for item in results if not eligible(item, filters)]
    return LabCheck(
        name="hard filters hold",
        passed=not violations,
        falsifier=(
            "any returned product violates the mission's domain, price ceiling, "
            "stock, or attribute predicate. Recovering recall by relaxing "
            "eligibility is not the repair."
        ),
        detail=(
            f"{len(results)} result(s) all satisfy {sorted(filters)}"
            if not violations
            else explain(
                f"product(s) {violations} outside filters {filters}",
                "keep the hard filter set on every candidate arm rather than "
                "widening it to recover the anchor",
            )
        ),
    )


def _lab_1_pool(response: Mapping[str, Any]) -> LabCheck:
    counts = (response.get("diagnostics") or {}).get("candidate_counts") or {}
    in_pool = counts.get("trigram_in_pool", 0)
    return LabCheck(
        name="trigram candidate pool non-empty",
        passed=in_pool > 0,
        falsifier=(
            "diagnostics.candidate_counts.trigram_in_pool is 0, the broken "
            "state's signature: the fuzzy arm contributed no candidate to "
            "fusion, whatever the result window happens to contain."
        ),
        detail=(
            f"trigram_in_pool={in_pool}"
            if in_pool > 0
            else explain(
                "diagnostics.candidate_counts.trigram_in_pool = 0",
                "restore the trigram CTE so mosaic_search.search_trigram "
                "contributes candidates to the fused pool",
            )
        ),
    )


def lab_1_checks(
    mission: Mapping[str, Any],
    response: Mapping[str, Any],
) -> list[LabCheck]:
    """Grade one search response against the Lab 1 acceptance conditions."""
    results = _results(response)
    return [
        _lab_1_anchor(mission, results),
        _lab_1_provenance(mission, results),
        _lab_1_filters(mission, results),
        _lab_1_pool(response),
    ]


# ---------------------------------------------------------------------------
# Lab 2 -- fuse, rerank, and inspect
# ---------------------------------------------------------------------------


def _contributions_consistent(result: Mapping[str, Any], rrf_k: int) -> bool:
    signals = _signals(result)
    expected = 0.0
    found = False
    for arm in ("fts", "trigram", "semantic"):
        signal = _arm(signals, arm)
        rank = signal.get("rank")
        contribution = signal.get("rrf_contribution")
        if rank is None:
            continue
        found = True
        if contribution is None or (
            abs(contribution - 1.0 / (rrf_k + rank)) > CONTRIBUTION_TOLERANCE
        ):
            return False
        expected += contribution
    rrf_score = signals.get("rrf_score", 0.0)
    return found and abs(rrf_score - expected) <= CONTRIBUTION_TOLERANCE


def _pre_rerank_order(results: Iterable[Mapping[str, Any]]) -> list[tuple[int, int]]:
    return sorted(
        (item["signals"]["pre_rerank_rank"], item["product_id"]) for item in results
    )


def _lab_2_arithmetic(response: Mapping[str, Any]) -> LabCheck:
    diagnostics = response.get("diagnostics") or {}
    rrf_k = (diagnostics.get("retrieval_profile") or {}).get("rrf_k")
    results = _results(response)
    if not isinstance(rrf_k, int):
        detail = explain(
            f"diagnostics.retrieval_profile.rrf_k = {rrf_k!r}",
            "request the search with include_diagnostics so the served profile "
            "reports the fusion constant this response was ranked with",
        )
        passed = False
    else:
        wrong = [
            item["product_id"]
            for item in results
            if not _contributions_consistent(item, rrf_k)
        ]
        passed = not wrong
        detail = (
            f"{len(results)} row(s) contribute 1 / (k + source_rank) at k={rrf_k}"
            if passed
            else explain(
                f"product(s) {wrong} whose contributions are not "
                f"1 / ({rrf_k} + source_rank)",
                "restore the reciprocal-rank formula in "
                "mosaic_search.reciprocal_rank_contribution",
            )
        )
    return LabCheck(
        name="RRF arithmetic correct",
        passed=passed,
        falsifier=(
            "a contribution differs from 1 / (k + source_rank), or the summed "
            "contributions differ from the fused score. The collapsed formula "
            "1 / (k + 1) ties every source position and still returns a "
            "plausible order, which is exactly why the arithmetic is checked "
            "rather than the ranking alone."
        ),
        detail=detail,
    )


def _lab_2_repeatable(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> LabCheck:
    first_order = _pre_rerank_order(_results(first))
    second_order = _pre_rerank_order(_results(second))
    return LabCheck(
        name="pre-rerank order repeatable",
        passed=first_order == second_order,
        falsifier=(
            "two identical requests fuse to different pre-rerank orders, which "
            "means the order depends on something other than the candidate "
            "ranks -- an unstable tie-break or a non-deterministic arm."
        ),
        detail=(
            f"{len(first_order)} row(s) fused identically across two runs"
            if first_order == second_order
            else explain(
                f"pre-rerank orders {first_order} then {second_order}",
                "make fusion break ties deterministically after relevance",
            )
        ),
    )


def _lab_2_rerank(response: Mapping[str, Any]) -> LabCheck:
    status = (response.get("diagnostics") or {}).get("rerank_status")
    return LabCheck(
        name="reranking bounded and applied",
        passed=status == "applied",
        falsifier=(
            "diagnostics.rerank_status is 'disabled' or 'unavailable', so the "
            "order being graded was never reranked and the lab's second stage "
            "did not run."
        ),
        detail=(
            "Cohere Rerank applied to the fused pool"
            if status == "applied"
            else explain(
                f"diagnostics.rerank_status = {status!r}",
                "request the search with rerank=true and confirm Bedrock "
                "rerank access before re-running the proof",
            )
        ),
    )


def _lab_2_provenance(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> LabCheck:
    target = _target(mission, results)
    signals = _signals(target)
    missing = [
        arm
        for arm in ("fts", "trigram", "semantic")
        if _arm(signals, arm).get("rank") is None
    ]
    rerank_score = signals.get("rerank_score")
    passed = target is not None and not missing and rerank_score is not None
    if target is None:
        detail = explain(
            f"no result carrying product id(s) "
            f"{sorted(mission.get('target_product_ids') or [])}",
            "run the mission query with its declared filters before grading "
            "the fusion repair",
        )
    elif passed:
        detail = (
            f"product {target['product_id']} retains every arm rank and a rerank score"
        )
    else:
        detail = explain(
            f"product {target['product_id']} missing arm rank(s) {missing} "
            f"and rerank_score={rerank_score!r}",
            "keep every source rank on the fused row so the ranking stays "
            "inspectable after reranking",
        )
    return LabCheck(
        name="rank provenance present",
        passed=passed,
        falsifier=(
            "the canonical winner is returned without one of its source ranks "
            "or without its reranker score, so the fused order cannot be "
            "attributed to the arms that produced it."
        ),
        detail=detail,
    )


def _lab_2_winner(
    mission: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> LabCheck:
    target = _target(mission, results)
    signals = _signals(target)
    pre_rerank_rank = signals.get("pre_rerank_rank")
    final_rank = signals.get("final_rank")
    arms_first = all(
        _arm(signals, arm).get("rank") == 1 for arm in ("fts", "trigram", "semantic")
    )
    passed = (
        target is not None and arms_first and pre_rerank_rank == 1 and final_rank == 1
    )
    if target is None:
        detail = explain(
            "no canonical winner in the result window",
            "run the mission query with its declared filters",
        )
    elif passed:
        detail = (
            f"product {target['product_id']} is rank 1 in every arm, fused "
            "rank 1, and final rank 1"
        )
    elif pre_rerank_rank != 1:
        detail = explain(
            f"product {target['product_id']} at pre_rerank_rank="
            f"{pre_rerank_rank!r}, not fused rank 1",
            "restore 1 / (k + source_rank) so a product that wins every arm "
            "also wins fusion",
        )
    else:
        detail = explain(
            f"product {target['product_id']} arms_rank_1={arms_first} "
            f"final_rank={final_rank!r}",
            "confirm the reranked window preserves the fused winner",
        )
    return LabCheck(
        name="canonical winner is fused and final rank 1",
        passed=passed,
        falsifier=(
            "the product that ranks first in all three arms is not fused rank "
            "1. Measured under the collapsed formula: product 370001 became "
            "fused rank 1 while Cohere still promoted 370002 to final rank 1, "
            "so a correct-looking answer masked broken fusion."
        ),
        detail=detail,
    )


def lab_2_checks(
    mission: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> list[LabCheck]:
    """Grade two identical search responses against Lab 2's conditions."""
    results = _results(first)
    return [
        _lab_2_arithmetic(first),
        _lab_2_repeatable(first, second),
        _lab_2_rerank(first),
        _lab_2_provenance(mission, results),
        _lab_2_winner(mission, results),
    ]


# ---------------------------------------------------------------------------
# Lab 3 -- the retrieval agent, graded over an HTTP response
# ---------------------------------------------------------------------------


def successful_steps(agent: Mapping[str, Any], tool: str) -> list[Mapping[str, Any]]:
    """Every successful trace step for one tool, in trace order."""
    return [
        step
        for step in agent.get("trace") or []
        if step.get("tool") == tool and step.get("outcome") == "success"
    ]


def explained_search_event_id(agent: Mapping[str, Any]) -> str | None:
    """The retrieval receipt the agent explained, if it explained exactly one."""
    explanations = successful_steps(agent, "explain_retrieval")
    if len(explanations) != 1:
        return None
    event_id = (explanations[0].get("arguments") or {}).get("search_event_id")
    return str(event_id) if event_id else None


def _targets_have_distinct_runs(
    targets: set[int],
    candidate_runs: Sequence[tuple[str, frozenset[int]]],
) -> bool:
    """Whether targets map to runs with distinct, non-empty queries."""
    ordered = sorted(
        targets,
        key=lambda target: sum(
            target in candidates for _, candidates in candidate_runs
        ),
    )

    def assign(position: int, used_runs: set[int], used_queries: set[str]) -> bool:
        if position == len(ordered):
            return True
        target = ordered[position]
        return any(
            assign(position + 1, used_runs | {index}, used_queries | {query})
            for index, (query, candidates) in enumerate(candidate_runs)
            if (
                index not in used_runs
                and query
                and query not in used_queries
                and target in candidates
            )
        )

    return assign(0, set(), set())


def _recommendation_ids(agent: Mapping[str, Any]) -> set[int]:
    return {int(item["product_id"]) for item in agent.get("recommendations") or []}


def _considered(evidence: AgentEvidence) -> set[int]:
    return {
        product_id
        for receipt in evidence.receipts
        for product_id in receipt.candidate_product_ids
    }


def _constraint_problem(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
) -> str | None:
    required = mission.get("filters") or {}
    dropped = [
        (step.get("arguments") or {}).get("query")
        for step in successful_steps(agent, "search_products")
        if not constraints_preserved(
            required, (step.get("arguments") or {}).get("applied_filters") or {}
        )
    ]
    if dropped:
        return explain(
            "Lab 3 retrieval trace does not preserve structured constraints on "
            f"search step(s) for {dropped}, against {required}",
            "pass the caller's structured envelope through to every "
            "search_products call rather than re-deriving it from the question",
        )
    ineligible = [
        item["product_id"]
        for item in agent.get("recommendations") or []
        if not eligible(item, required)
    ]
    if ineligible:
        return explain(
            f"Lab 3 recommendation violates structured constraints: "
            f"product(s) {ineligible} outside {required}",
            "recommend only products the filtered retrieval returned",
        )
    return None


def _check_constraints(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
) -> LabCheck:
    problem = _constraint_problem(mission, agent)
    required = mission.get("filters") or {}
    return LabCheck(
        name="structured constraints preserved",
        passed=problem is None,
        falsifier=(
            "a model-issued search widens or drops the caller's domain, price "
            "ceiling, stock, or jsonb attribute predicate, or a recommendation "
            "falls outside it. The trace reads plausibly either way, which is "
            "why the envelope is compared rather than the prose."
        ),
        detail=problem or f"every search and recommendation held {sorted(required)}",
    )


def _check_target_coverage(
    mission: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    targets = {int(item) for item in mission.get("target_product_ids") or []}
    missing = sorted(targets - _considered(evidence))
    return LabCheck(
        name="canonical target classes covered",
        passed=not missing,
        falsifier=(
            "a declared target class appears in no persisted retrieval receipt, "
            "so the agent answered about a product it never actually retrieved."
        ),
        detail=(
            f"{len(evidence.receipts)} receipt(s) cover targets {sorted(targets)}"
            if not missing
            else explain(
                f"Lab 3 retrieval runs missed canonical target classes {missing}",
                "issue focused searches that cover every declared target_product_id",
            )
        ),
    )


def _check_independent_intents(
    mission: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    targets = {int(item) for item in mission.get("target_product_ids") or []}
    runs = [
        (receipt.query.strip().casefold(), receipt.candidate_product_ids)
        for receipt in evidence.receipts
    ]
    distinct_queries = {query for query, _ in runs if query}
    passed = (
        len(runs) >= len(targets)
        and len(distinct_queries) >= len(targets)
        and _targets_have_distinct_runs(targets, runs)
    )
    return LabCheck(
        name="independent retrieval intents covered",
        passed=passed,
        falsifier=(
            "one broad search covers every target, or a decoy query pads the "
            "receipt count without binding a distinct query to each target "
            "class. Both leave the agent's multi-intent decomposition unproven."
        ),
        detail=(
            f"{len(distinct_queries)} distinct focused query text(s) bind to "
            f"targets {sorted(targets)}"
            if passed
            else explain(
                "Lab 3 independent intent proof requires one distinct focused "
                f"search and retrieval receipt per target class; "
                f"{len(distinct_queries)} query text(s), {len(runs)} receipt(s), "
                f"targets {sorted(targets)}",
                "issue one focused search per target class",
            )
        ),
    )


def _check_tools_invoked(
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    searches = successful_steps(agent, "search_products")
    comparisons = successful_steps(agent, "compare_products")
    recommended = _recommendation_ids(agent)
    compared = {
        int(product_id)
        for step in comparisons
        for product_id in (step.get("arguments") or {}).get("product_ids", [])
    }
    ungrounded = sorted(recommended - _considered(evidence))
    problems = []
    if not searches:
        problems.append("Lab 3 did not invoke search_products successfully")
    if not comparisons:
        problems.append("Lab 3 did not invoke compare_products successfully")
    if len(recommended) < 2:
        problems.append("Lab 3 did not return a comparison shortlist")
    elif len(compared & recommended) < 2:
        problems.append("Lab 3 comparison does not cover the recommendation shortlist")
    if ungrounded:
        problems.append(
            f"Lab 3 recommended product(s) {ungrounded} absent from persisted "
            "retrieval receipts"
        )
    return LabCheck(
        name="retrieval and comparison tools invoked",
        passed=not problems,
        falsifier=(
            "the shortlist is produced without a successful retrieval or "
            "comparison call, or names a product no receipt granted -- the "
            "shape of an answer the model wrote rather than retrieved."
        ),
        detail=(
            f"{len(searches)} search(es) and {len(comparisons)} comparison(s) "
            f"produced a shortlist of {len(recommended)}"
            if not problems
            else explain(
                "; ".join(problems),
                "let the tools produce the shortlist and compare it before synthesis",
            )
        ),
    )


def _check_evidence_retrieved(agent: Mapping[str, Any]) -> LabCheck:
    steps = successful_steps(agent, "get_product_evidence")
    covered = {
        int((step.get("arguments") or {})["product_id"])
        for step in steps
        if (step.get("arguments") or {}).get("product_id") is not None
    }
    recommended = _recommendation_ids(agent)
    missing = sorted(recommended - covered)
    empty = [step for step in steps if (step.get("result_count") or 0) <= 0]
    passed = not missing and not empty and bool(steps)
    if missing:
        detail = explain(
            f"no successful get_product_evidence call for product(s) {missing}",
            "retrieve evidence for every recommended product before synthesis",
        )
    elif empty or not steps:
        detail = explain(
            f"{len(empty)} evidence call(s) returned no records"
            if steps
            else "no successful get_product_evidence call at all",
            "check the evidence tool returns records for the recommended "
            "products before citing them",
        )
    else:
        detail = f"{len(steps)} evidence call(s) cover {len(recommended)} product(s)"
    return LabCheck(
        name="evidence retrieved for every recommendation",
        passed=passed,
        falsifier=(
            "a recommended product has no successful evidence call, or the "
            "evidence tool returned zero records for one. Either way the "
            "citation that follows is unsupported."
        ),
        detail=detail,
    )


def _explanation_problem(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> str | None:
    explanations = successful_steps(agent, "explain_retrieval")
    if len(explanations) != 1:
        return explain(
            "Lab 3 requires exactly one successful explain_retrieval tool call "
            f"before synthesis; found {len(explanations)}",
            "explain exactly one persisted retrieval receipt",
        )
    event_id = explained_search_event_id(agent)
    receipt_ids = {receipt.search_event_id for receipt in evidence.receipts}
    if event_id not in receipt_ids:
        return explain(
            "Lab 3 explain_retrieval is not bound to a persisted retrieval "
            f"receipt; {event_id!r}, expected one of {sorted(receipt_ids)}",
            "explain a search_event_id this turn actually produced",
        )
    if not mission.get("requires_explain_plan"):
        return None
    if not _is_plan(evidence.captured_plan):
        return explain(
            "Lab 3 EXPLAIN activity returned no PostgreSQL JSON plan",
            "use the production plan-capture endpoint for the explained "
            "retrieval event",
        )
    if evidence.replayed_plan != evidence.captured_plan:
        return explain(
            "Lab 3 EXPLAIN plan was not persisted on the explained retrieval event",
            "replay the same event after plan capture",
        )
    return None


def _check_ranking_explanation(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    problem = _explanation_problem(mission, agent, evidence)
    return LabCheck(
        name=(
            "ranking explanation and EXPLAIN plan replayable"
            if mission.get("requires_explain_plan")
            else "ranking explanation replayable"
        ),
        passed=problem is None,
        falsifier=(
            "the explanation names no persisted receipt, names one from "
            "another turn, or -- when the mission requires it -- the captured "
            "EXPLAIN plan never lands on the event, so the ranking cannot be "
            "replayed from Aurora afterwards."
        ),
        detail=problem
        or f"explained receipt {explained_search_event_id(agent)} replays",
    )


def _is_plan(plan: Any) -> bool:
    return (
        isinstance(plan, list)
        and bool(plan)
        and all(
            isinstance(statement, dict) and isinstance(statement.get("Plan"), dict)
            for statement in plan
        )
    )


def _check_execution_origins(agent: Mapping[str, Any]) -> LabCheck:
    trace = agent.get("trace") or []
    unattributed = [
        step.get("tool")
        for step in trace
        if step.get("origin") not in {"model", "controller_fallback"}
    ]
    return LabCheck(
        name="tool execution origins explicit",
        passed=not unattributed and bool(trace),
        falsifier=(
            "a trace step does not identify model versus controller execution "
            "origin, so a controller fallback is indistinguishable from a "
            "decision the model actually made."
        ),
        detail=(
            f"{len(trace)} step(s) declare an execution origin"
            if trace and not unattributed
            else explain(
                f"Lab 3 trace does not identify model versus controller "
                f"execution origin for step(s) {unattributed}"
                if unattributed
                else "an empty tool trace",
                "record origin on every trace step",
            )
        ),
    )


def _citation_resolves(
    citation: Mapping[str, Any],
    resolved: Mapping[str, Any] | None,
) -> bool:
    return bool(resolved) and all(
        resolved.get(field_name) == citation[citation_key]
        for field_name, citation_key in (
            ("evidence_id", "evidence_id"),
            ("product_id", "product_id"),
            ("source_uri", "source_uri"),
            ("revision", "revision"),
            ("text", "quote"),
        )
    )


def _citation_problem(
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> str | None:
    citations = agent.get("citations") or []
    if not citations:
        return explain(
            "Lab 3 returned no citations",
            "let grounded synthesis attach the evidence it retrieved",
        )
    recommended = _recommendation_ids(agent)
    cited = {int(citation["product_id"]) for citation in citations}
    if not recommended <= cited:
        return explain(
            "Lab 3 did not cite evidence for every recommended product; "
            f"uncited {sorted(recommended - cited)}",
            "cite at least one evidence record per recommendation",
        )
    unresolved = [
        citation["number"]
        for citation in citations
        if not _citation_resolves(
            citation, evidence.resolved_evidence.get(citation["evidence_id"])
        )
        or int(citation["product_id"]) not in recommended
    ]
    if unresolved:
        return explain(
            f"Lab 3 citation {unresolved[0]} does not resolve exactly",
            "return citation IDs that address the evidence rows the evidence "
            "tool actually returned",
        )
    return None


def _check_citations_resolve(
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    problem = _citation_problem(agent, evidence)
    citations = agent.get("citations") or []
    return LabCheck(
        name="citation IDs resolve exactly",
        passed=problem is None,
        falsifier=(
            "a citation id resolves to a different product, quote, or "
            "revision, resolves to nothing, or a recommendation carries no "
            "citation at all -- the signature of an answer written around "
            "evidence rather than from it."
        ),
        detail=problem
        or f"{len(citations)} citation(s) resolve to their evidence rows",
    )


def _normalize(text: str) -> str:
    return text.casefold().replace("_", " ").replace("-", " ")


def _check_required_claims(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> LabCheck:
    requirements = mission.get("required_citation_support") or []
    resolved = [
        {**evidence.resolved_evidence.get(citation["evidence_id"], {}), **citation}
        for citation in agent.get("citations") or []
    ]
    unsupported = [
        requirement
        for requirement in requirements
        if not any(
            item.get("product_id") == requirement["product_id"]
            and item.get("evidence_type") == requirement["evidence_type"]
            and all(
                _normalize(term) in _normalize(str(item.get("text") or ""))
                for term in requirement["all_terms"]
            )
            for item in resolved
        )
    ]
    return LabCheck(
        name="required claims supported",
        passed=not unsupported,
        falsifier=(
            "the mission's declared claim has no cited evidence row containing "
            "its terms, so the answer asserts a specification the catalog "
            "never backed."
        ),
        detail=(
            f"{len(requirements)} declared claim(s) supported by cited evidence"
            if not unsupported
            else explain(
                "Lab 3 required citation support is absent for product "
                f"{unsupported[0]['product_id']}: evidence_type="
                f"{unsupported[0]['evidence_type']}, "
                f"terms={unsupported[0]['all_terms']}",
                "cite an evidence record that states the claim",
            )
        ),
    )


def agent_response_checks(
    mission: Mapping[str, Any],
    agent: Mapping[str, Any],
    evidence: AgentEvidence,
) -> list[LabCheck]:
    """Grade one agent response plus its fetched receipts against Lab 3.

    Target coverage is graded before independence deliberately: when a target
    appears in no receipt at all, "you missed a target class" is the actionable
    message, and "your searches were not independent" is a consequence of it.
    """
    checks = [
        _check_constraints(mission, agent),
        _check_target_coverage(mission, evidence),
    ]
    if mission.get("requires_independent_target_searches"):
        checks.append(_check_independent_intents(mission, evidence))
    checks.extend(
        [
            _check_tools_invoked(agent, evidence),
            _check_evidence_retrieved(agent),
            _check_ranking_explanation(mission, agent, evidence),
            _check_execution_origins(agent),
            _check_citations_resolve(agent, evidence),
            _check_required_claims(mission, agent, evidence),
        ]
    )
    return checks


# ---------------------------------------------------------------------------
# Lab 3 -- the retrieval agent, graded over persisted rows
# ---------------------------------------------------------------------------

STAGE_03_FIX = (
    "run Stage 03 (Reason) on the Retrieval Lab page, then submit the "
    "agent_run_id it returns"
)
_MISSING_RUN = explain(
    "no persisted agent turn for the submitted agent_run_id, so Stage 03 "
    "produced no receipts to grade",
    STAGE_03_FIX,
)


def _proof_check(
    name: str,
    *,
    passed: bool,
    falsifier: str,
    detail: str,
    run: PersistedAgentRun | None,
) -> LabCheck:
    """One persisted-row check, forced to fail when no run exists to read."""
    return LabCheck(
        name=name,
        passed=passed and run is not None,
        falsifier=falsifier,
        detail=detail if run is not None else _MISSING_RUN,
    )


def _proof_answer(run: PersistedAgentRun | None) -> LabCheck:
    message = (run.assistant_message or "") if run else ""
    return _proof_check(
        "answer of record present",
        passed=bool(message.strip()),
        falsifier=(
            "mosaic.agent_turn.assistant_message is null: Stage 03 never wrote "
            "an answer of record, which is what an ungrounded run looks like "
            "once the evidence state is detached from synthesis."
        ),
        detail=(
            f"{len(message)} character answer of record persisted"
            if message.strip()
            else explain(
                "mosaic.agent_turn.assistant_message is empty",
                STAGE_03_FIX,
            )
        ),
        run=run,
    )


def _proof_synthesis(run: PersistedAgentRun | None) -> LabCheck:
    outcome = run.synthesis_outcome if run else None
    scope = run.selected_products if run else ()
    return _proof_check(
        "grounded synthesis produced a product scope",
        passed=outcome == "success" and bool(scope),
        falsifier=(
            "the synthesize_cited_answer tool event is absent or not "
            "successful, or the turn's extracted_intent carries no selected "
            "product. Both are the broken Lab 3 state: evidence reaches the "
            "model but never reaches grounded synthesis."
        ),
        detail=(
            f"synthesis succeeded over products {sorted(scope)}"
            if outcome == "success" and scope
            else explain(
                f"synthesize_cited_answer outcome={outcome!r} over "
                f"{len(scope)} selected product(s)",
                "attach retrieved evidence IDs to agent state by product "
                "before synthesis, then re-run Stage 03",
            )
        ),
        run=run,
    )


def _unresolved_citations(run: PersistedAgentRun | None) -> list[int]:
    if run is None:
        return []
    return [
        citation["evidence_id"]
        for citation in run.citations
        if (run.resolved_evidence.get(citation["evidence_id"]) or {}).get("product_id")
        != citation["product_id"]
    ]


def _proof_citations(run: PersistedAgentRun | None) -> LabCheck:
    citations = run.citations if run else ()
    unresolved = _unresolved_citations(run)
    return _proof_check(
        "citation evidence resolves",
        passed=bool(citations) and not unresolved,
        falsifier=(
            "the persisted citations are empty, or an evidence id resolves to "
            "a different product than the citation claims, so the answer of "
            "record is not addressable back to the catalog."
        ),
        detail=(
            f"{len(citations)} citation(s) resolve to their evidence rows"
            if citations and not unresolved
            else explain(
                f"evidence id(s) {unresolved} resolving to another product"
                if unresolved
                else "no citation on the persisted synthesis event",
                "return citation IDs that address the evidence rows the "
                "evidence tool returned",
            )
        ),
        run=run,
    )


def _proof_evidence(run: PersistedAgentRun | None) -> LabCheck:
    events = run.evidence_events if run else ()
    successful = [event for event in events if event.get("outcome") == "success"]
    empty = [
        event["product_id"]
        for event in successful
        if (event.get("result_count") or 0) <= 0
    ]
    covered = {
        event["product_id"]
        for event in successful
        if (event.get("result_count") or 0) > 0
    }
    missing = sorted(set(run.selected_products) - covered) if run else []
    return _proof_check(
        "product evidence retrieved",
        passed=bool(successful) and not empty and not missing,
        falsifier=(
            "no successful get_product_evidence tool event exists, one "
            "returned zero records, or a selected product has none, so a "
            "citation on that product cites nothing that was fetched."
        ),
        detail=(
            f"{len(successful)} evidence event(s) cover {sorted(covered)}"
            if successful and not empty and not missing
            else explain(
                f"{len(successful)} successful evidence event(s), empty for "
                f"{empty}, missing for {missing}",
                "retrieve evidence for every selected product before "
                "synthesis, then re-run Stage 03",
            )
        ),
        run=run,
    )


def _proof_envelope(
    mission: Mapping[str, Any],
    run: PersistedAgentRun | None,
) -> LabCheck:
    required = mission.get("filters") or {}
    persisted = run.search_filters if run else ()
    widened = [
        dict(applied)
        for applied in persisted
        if not constraints_preserved(required, applied)
    ]
    return _proof_check(
        "retrieval envelope preserved",
        passed=bool(persisted) and not widened,
        falsifier=(
            "the turn linked no search_event at all, or a persisted "
            "mosaic.search_event.filters row widened the mission's domain, "
            "price ceiling, or stock predicate. An empty list is a failure "
            "rather than a vacuous pass, because zero searches is exactly what "
            "a turn that answered from the model looks like."
        ),
        detail=(
            f"{len(persisted)} persisted search filter row(s) held {sorted(required)}"
            if persisted and not widened
            else explain(
                f"{len(persisted)} persisted search filter row(s), widened by {widened}"
                if persisted
                else "no mosaic.search_event row linked to this turn",
                f"keep {sorted(required)} on every agent-issued search",
            )
        ),
        run=run,
    )


def lab_3_proof_checks(
    mission: Mapping[str, Any],
    run: PersistedAgentRun | None,
) -> list[LabCheck]:
    """Grade one persisted agent turn against the Lab 3 completion conditions.

    `run` is `None` when no turn is persisted for the submitted id. Every check
    is still returned, failed, naming Stage 03 -- so the count stays a stable
    witness and the participant is told where to produce a run rather than
    reading an empty list as a pass.
    """
    return [
        _proof_answer(run),
        _proof_synthesis(run),
        _proof_citations(run),
        _proof_evidence(run),
        _proof_envelope(mission, run),
    ]
