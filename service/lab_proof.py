"""Lab state and completion proof: the two "did I finish?" answers, served.

Until this module the only answers were on the terminal. `scripts/lab_state.py`
reports the marker blocks a participant edited and `scripts/validate_lab.py`
grades a running API, and neither is reachable from the browser the workshop is
otherwise driven from.

Three deliberate boundaries:

* The checks live in `service.lab_checks`, not here. This module fetches
  evidence and assembles a response; it never decides what passing means.
* Labs 1 and 2 re-run their mission through
  `service.telemetry.search_with_telemetry` -- the same call `POST /api/search`
  makes -- so the proof is graded on a real retrieval with a real receipt,
  not on a reimplementation. Lab 2 repeats its primary mission to prove
  repeatability. Both labs also run the manifest's required supporting controls.
* Lab 3 grades persisted rows and spends no agent turn. If its explained
  retrieval has no saved EXPLAIN plan, the proof captures and replays one.
  Re-running the agent would spend another turn and grade a fresh
  run rather than the one the participant is looking at.

`status` is the conjunction of three separate facts: every check passed, the
source seam is repaired, and Aurora holds that repair. Checks alone are not
enough -- a Lab 3 run persisted before the source was re-broken would still
grade green on its own receipts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

import psycopg

from scripts.lab_entry import (
    FAULT_AT_ENTRY,
    START_COMMAND,
    completion_path,
    load_record,
)
from scripts.lab_state import (
    LABS,
    LabDatabaseState,
    lab_is_solved,
    validate_database,
)
from scripts.lab_state import (
    REPO as LAB_SOURCE_ROOT,
)
from service import lab_checks
from service.catalog import get_evidence_record
from service.config import get_settings
from service.db import connect
from service.lab_checks import (
    AgentEvidence,
    LabCheck,
    PersistedAgentRun,
    RetrievalReceipt,
)
from service.models import (
    CompletionProofEvidence,
    CompletionProofIdentity,
    CompletionProofResponse,
    LabCheckResult,
    LabStateRecord,
    LabStateResponse,
    ReleaseBaselineReference,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)
from service.retrieval import get_retrieval_service
from service.retrieval_fingerprint import (
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
    explain,
)
from service.retrieval_replay import load_candidate_receipts
from service.scorecard import retrieval_scorecard
from service.telemetry import search_with_telemetry
from service.telemetry_contract import AgentTurnRows, load_agent_turn_rows

#: The three labs, in the order the session runs them.
LAB_IDS: tuple[int, ...] = (1, 2, 3)

#: How many identical searches each lab's proof issues. Lab 2 needs two,
#: because "the pre-rerank order is repeatable" is not answerable from one.
SEARCHES_PER_LAB: dict[int, int] = {1: 1, 2: 2, 3: 0}


class UnknownLab(LookupError):
    """A lab number this workshop does not have."""


def _require_lab(lab_id: int) -> None:
    if lab_id not in LAB_IDS:
        raise UnknownLab(
            explain(
                f"lab_id {lab_id}",
                f"use one of {list(LAB_IDS)}; the session has three required "
                "labs and gains no more",
            )
        )


def resolve_evidence(evidence_id: int) -> Mapping[str, Any]:
    """One evidence row, through the lookup `GET /api/evidence/{id}` serves.

    Returns an empty mapping for an id that resolves to nothing, which the
    citation check reads as a failure rather than as an absent comparison.
    """
    try:
        return get_evidence_record(evidence_id).model_dump(mode="json")
    except KeyError:
        return {}


def _state_detail(
    lab_id: int,
    *,
    solved: bool,
    database: LabDatabaseState,
) -> str:
    if lab_id == 3:
        from service.agent_setup import AGENT_STARTER_MESSAGE

        return (
            "Your agent code is ready. Next: run make deploy-agent, then ask Alex's question in Mosaic."
            if solved
            else AGENT_STARTER_MESSAGE
        )
    if not solved:
        return (
            f"Lab {lab_id} needs its SQL change. Open {LABS[lab_id][0]} in Code Editor "
            f"and find the LAB{lab_id}_ markers. Next: complete the marked block, "
            f"run make db-apply-search-functions, then make validate-lab-{lab_id}."
        )
    if database.state == "stale":
        return database.detail
    return f"Lab {lab_id} source is repaired and {database.detail}"


def contained_database_state(lab_id: int, connection: Any) -> LabDatabaseState:
    """Read one lab's Aurora state inside its own transaction.

    `GET /api/labs/state` grades three labs over one pooled connection, and
    `scripts.lab_state._lab_1_database_state` casts a signature to
    `regprocedure`: a missing or re-headed `search_hybrid_rrf` raises
    `psycopg.errors.UndefinedFunction`, which is not a `RuntimeError` and
    aborts the surrounding transaction. Uncontained, one bad lab both returned
    a 500 and left the next lab's read failing on an aborted transaction.
    Each lab's read runs inside its own `connection.transaction()`. The
    pool hands over an idle connection, so that block is a top-level
    transaction, not a savepoint: a failure rolls back completely and the
    next lab starts clean on the same connection.

    An absent function is reported as `stale` naming only the exception type,
    never the connection: a participant who edited the SQL and did not re-apply
    it sees the same verdict and the same fix either way.

    An `OperationalError` -- pool timeouts included, which subclass it -- is
    re-raised. The connection itself is gone, which is the route's 503 and not
    a claim about what Aurora holds.
    """
    try:
        with connection.transaction():
            return validate_database(lab_id, connection)
    except psycopg.DatabaseError as error:
        if isinstance(error, psycopg.OperationalError):
            raise
        return LabDatabaseState(
            state="stale",
            detail=explain(
                f"reading the Lab {lab_id} state from Aurora raised "
                f"{type(error).__name__}",
                f"run make solution-lab-{lab_id}, or re-apply the edited file "
                "with make db-apply-search-functions",
            ),
        )


#: Said beside a failing Lab 1 proof while Lab 2's fault is installed, so the
#: participant is not sent to repair a lab that is already repaired.
LAB1_UNDER_RANKING_FAULT = (
    "Lab 2's ranking fault is installed. It gives every search method's candidates "
    "the same 1/(k + 1) credit, so the swapped-ID listing ties with other headphones "
    "and can fall outside the candidates sent to reranking. Your Lab 1 repair is "
    "still in the file and in Aurora; this check runs normally once Lab 2 is repaired."
)


def ranking_fault_masks_lab_1(connection: Any, repo: Path) -> bool:
    """Whether a repaired Lab 1 is being graded through Lab 2's installed fault.

    Only then does a failing Lab 1 check say nothing about Lab 1's own repair.
    """
    lab_1_repaired = (
        lab_is_solved(1, repo=repo)
        and contained_database_state(1, connection).state == "applied"
    )
    return lab_1_repaired and (
        not lab_is_solved(2, repo=repo)
        or contained_database_state(2, connection).state == "stale"
    )


def _saved_completion_at(lab_id: int, repo: Path) -> datetime | None:
    path = completion_path(lab_id, repo)
    if not path.exists():
        return None
    return datetime.fromisoformat(json.loads(path.read_text())["passed_at"])


def _entry(lab_id: int, repo: Path) -> tuple[str | None, str | None]:
    """Where an entered lab's one-time preparation stands, and what runs it."""
    if lab_id not in FAULT_AT_ENTRY:
        return None, None
    record = load_record(lab_id, repo)
    if record is None:
        return "not_started", START_COMMAND[lab_id]
    if not record.get("completed_at"):
        return "incomplete", START_COMMAND[lab_id]
    return "started", None


def entry_check(
    lab_id: int, repo: Path, *, run_created_at: datetime | None = None
) -> LabCheck:
    """Refuse to credit an entered lab's shipped reference as the participant's repair.

    The checkout ships Labs 2 and 3 repaired, so before a start their checks
    grade code nobody wrote. A Lab 3 run made before the start graded that
    same reference agent.
    """
    record = load_record(lab_id, repo)
    started = record.get("completed_at") if record else None
    started_at = datetime.fromisoformat(started) if started else None
    if started_at is None:
        passed = False
        detail = (
            f"Lab {lab_id} has not started, so these checks would grade the "
            f"reference the workshop ships. Next: run {START_COMMAND[lab_id]}, "
            "repair the fault it installs, then prove the lab again."
        )
    elif run_created_at is not None and run_created_at < started_at:
        passed = False
        detail = (
            f"This run was made before Lab {lab_id} started, by the reference "
            "agent. Next: after make deploy-agent, ask Alex's question again and "
            "use that run's ID."
        )
    else:
        passed = True
        detail = f"Lab {lab_id} started at {started_at:%H:%M:%S} UTC."
    return LabCheck(
        name="lab_started",
        passed=passed,
        falsifier=(
            "The lab's start has not finished, or the graded run predates it, so "
            "the shipped reference would be credited as the participant's repair."
        ),
        detail=detail,
    )


def _lab_state(lab_id: int, connection: Any, repo: Path | None) -> LabStateRecord:
    root = repo or LAB_SOURCE_ROOT
    solved = lab_is_solved(lab_id, repo=root)
    database = contained_database_state(lab_id, connection)
    entry_state, next_step = _entry(lab_id, root)
    detail = _state_detail(lab_id, solved=solved, database=database)
    if entry_state == "not_started":
        detail = (
            f"Lab {lab_id} has not started. Next: run {next_step} in Code Editor; "
            "it installs this lab's fault once and keeps your earlier repairs."
        )
    elif entry_state == "incomplete":
        detail = (
            f"Lab {lab_id}'s start was interrupted. Next: run {next_step} again; "
            "it finishes the missing step and keeps your edits."
        )
    return LabStateRecord(
        lab_id=lab_id,
        source_state="solved" if solved else "broken",
        database_state=database.state,
        detail=detail,
        entry_state=entry_state,
        completed_at=_saved_completion_at(lab_id, root),
        next_step=next_step,
    )


def lab_states(*, repo: Path | None = None) -> LabStateResponse:
    """Report both halves of each lab's state, over one pooled connection.

    Args:
        repo: Repository root whose marker blocks are read. Defaults to the
            running checkout; tests pass a copy so a reset can be observed
            without editing the working tree.
    """
    with connect() as connection:
        return LabStateResponse(
            labs=[_lab_state(lab_id, connection, repo) for lab_id in LAB_IDS]
        )


def _mission_search(mission: Mapping[str, Any]) -> SearchResponse:
    """Run the mission exactly as the search route would run it."""
    return search_with_telemetry(
        SearchRequest(
            query=mission["query"],
            filters=SearchFilters(**mission["filters"]),
            limit=mission["top_k"],
            include_diagnostics=True,
            rerank=True,
        )
    )


def _retrieval_checks(
    lab_id: int,
    mission: Mapping[str, Any],
) -> tuple[list[LabCheck], list[UUID]]:
    responses = [_mission_search(mission) for _ in range(SEARCHES_PER_LAB[lab_id])]
    graded = [response.model_dump(mode="json") for response in responses]
    checks = (
        lab_checks.lab_1_checks(mission, graded[0])
        if lab_id == 1
        else lab_checks.lab_2_checks(mission, graded[0], graded[1])
    )
    for control in lab_checks.supporting_checks_for_lab(lab_id):
        response = _mission_search(control)
        with connect() as connection:
            candidates = load_candidate_receipts(connection, response.search_event_id)
        checks.extend(
            lab_checks.retrieval_control_checks(
                control, response.model_dump(mode="json"), candidates
            )
        )
        responses.append(response)
    return checks, [response.search_event_id for response in responses]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _selected_products(turn: Mapping[str, Any]) -> tuple[int, ...]:
    intent = _as_dict(turn.get("extracted_intent"))
    return tuple(
        int(item["product_id"])
        for item in intent.get("selected_products") or []
        if isinstance(item, dict) and item.get("product_id") is not None
    )


def _synthesis_event(tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            tool
            for tool in reversed(tools)
            if tool.get("tool_name") == "synthesize_cited_answer"
        ),
        None,
    )


def _evidence_events(tools: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "product_id": _as_dict(tool.get("input_payload")).get("product_id"),
            "outcome": tool.get("outcome"),
            "result_count": _as_dict(tool.get("output_payload")).get("result_count"),
        }
        for tool in tools
        if tool.get("tool_name") == "get_product_evidence"
    )


def _persisted_run(rows: AgentTurnRows) -> PersistedAgentRun:
    """Reduce one loaded turn to the facts Lab 3's proof grades.

    Evidence is resolved here, after the loading connection is released:
    `service.db.connect` is not re-entrant, and `get_evidence_record` opens its
    own.
    """
    synthesis = _synthesis_event(rows.tools)
    citations = tuple(
        citation
        for citation in _as_dict(
            synthesis.get("output_payload") if synthesis else None
        ).get("citations")
        or []
        if isinstance(citation, dict)
    )
    return PersistedAgentRun(
        agent_run_id=str(rows.turn["agent_turn_id"]),
        assistant_message=rows.turn.get("assistant_message"),
        selected_products=_selected_products(rows.turn),
        synthesis_outcome=synthesis.get("outcome") if synthesis else None,
        citations=citations,
        resolved_evidence={
            citation["evidence_id"]: resolve_evidence(citation["evidence_id"])
            for citation in citations
            if citation.get("evidence_id") is not None
        },
        evidence_events=_evidence_events(rows.tools),
        search_filters=tuple(
            _as_dict(search.get("filters")) for search in rows.searches
        ),
        outcome=_as_dict(rows.turn.get("extracted_intent")).get("outcome"),
    )


def _persisted_mission_checks(
    mission: Mapping[str, Any],
    rows: AgentTurnRows | None,
    run: PersistedAgentRun | None,
    requested_run_id: str | None,
) -> list[LabCheck]:
    if rows is None or run is None:
        missing = lab_checks.missing_run_detail(requested_run_id)
        return [
            LabCheck(check.name, False, check.falsifier, missing)
            for check in lab_checks.agent_response_checks(mission, {}, AgentEvidence())
        ]
    trace = [
        {
            "tool": tool["tool_name"],
            "outcome": tool.get("outcome"),
            "origin": tool.get("execution_origin"),
            "arguments": _as_dict(tool.get("input_payload")),
            "result_count": _as_dict(tool.get("output_payload")).get("result_count"),
            "retrieval_run_id": str(tool["search_event_id"])
            if tool.get("search_event_id")
            else None,
        }
        for tool in rows.tools
    ]
    agent = {
        "question": rows.turn.get("user_message"),
        "answer": run.assistant_message,
        "recommendations": _as_dict(rows.turn.get("extracted_intent")).get(
            "selected_products"
        )
        or [],
        "trace": trace,
        "citations": run.citations,
    }
    receipts = tuple(
        RetrievalReceipt(
            str(search["search_event_id"]),
            search.get("query_text") or "",
            frozenset(
                int(row["product_id"])
                for row in rows.candidates
                if row["search_event_id"] == search["search_event_id"]
            ),
        )
        for search in rows.searches
    )
    explained = lab_checks.explained_search_event_id(agent)
    search = next(
        (
            search
            for search in rows.searches
            if str(search["search_event_id"]) == explained
        ),
        None,
    )
    captured = search.get("plan_json") if search else None
    replayed = captured
    if (
        mission.get("requires_explain_plan")
        and search
        and captured is None
        and run.synthesis_outcome == "success"
    ):
        captured = get_retrieval_service().capture_plan(UUID(explained)).plan
        with connect() as connection:
            replayed = connection.execute(
                "SELECT plan_json FROM mosaic.search_event WHERE search_event_id = %s",
                (UUID(explained),),
            ).fetchone()["plan_json"]
    evidence = AgentEvidence(receipts, run.resolved_evidence, captured, replayed)
    return lab_checks.agent_response_checks(mission, agent, evidence)


def _identity() -> CompletionProofIdentity:
    settings = get_settings()
    return CompletionProofIdentity(
        source_revision=settings.source_revision,
        retrieval_fingerprint=compute_retrieval_fingerprint(),
        retrieval_settings_sha256=compute_live_retrieval_settings_sha256(),
        embedding_model_id=settings.embedding_model_id,
        rerank_model_id=settings.rerank_model_id,
        dataset_manifest_sha256=settings.dataset_manifest_sha256,
    )


def _release_baseline() -> ReleaseBaselineReference:
    """The maintainers' measured artifact, as context and never as the verdict.

    `attributed` is normally false mid-lab: the participant edits a file the
    retrieval fingerprint covers, so the running tree stops matching the tree
    the baseline was measured on. That is correct, and it is exactly why the
    lab verdict above is computed from live checks instead of from this.
    """
    provenance = retrieval_scorecard().provenance
    return ReleaseBaselineReference(
        measured_at=provenance.measured_at,
        retrieval_fingerprint=provenance.retrieval_fingerprint,
        attributed=provenance.attributed,
    )


def _served(check: LabCheck) -> LabCheckResult:
    return LabCheckResult(
        name=check.name,
        passed=check.passed,
        falsifier=check.falsifier,
        detail=check.detail,
    )


def completion_proof(
    lab_id: int,
    *,
    agent_run_id: UUID | None = None,
    repo: Path | None = None,
) -> CompletionProofResponse:
    """Prove one lab is finished, against Aurora, right now.

    Args:
        lab_id: The lab to grade, 1 to 3.
        agent_run_id: The persisted turn Lab 3 grades. Required there; the
            proof spends no agent turn of its own, so it has to be told which
            run to read. Ignored by labs 1 and 2.
        repo: Repository root whose marker blocks are read. Defaults to the
            running checkout.

    Returns:
        The verdict, the checks behind it, the receipts it produced or read,
        and the retrieval identity that produced them.

    Raises:
        UnknownLab: The lab number is not one of the three.
    """
    _require_lab(lab_id)
    mission = lab_checks.mission_for_lab(lab_id)
    started_at = datetime.now(UTC)
    started = perf_counter()

    root = repo or LAB_SOURCE_ROOT
    solved = lab_is_solved(lab_id, repo=root)
    with connect() as connection:
        database = contained_database_state(lab_id, connection)
        ranking_fault = lab_id == 1 and ranking_fault_masks_lab_1(connection, root)
        rows = (
            load_agent_turn_rows(connection, agent_run_id)
            if lab_id == 3 and agent_run_id is not None
            else None
        )

    if lab_id == 3:
        run = _persisted_run(rows) if rows is not None else None
        checks = lab_checks.lab_3_proof_checks(
            mission,
            run,
            requested_run_id=str(agent_run_id) if agent_run_id is not None else None,
        )
        checks.extend(
            _persisted_mission_checks(
                mission, rows, run, str(agent_run_id) if agent_run_id else None
            )
        )
        from service import agentcore_transport, gateway_tools

        if agentcore_transport.runtime_arn():
            from scripts.apply_search_functions import applied_sql_digest
            from service.lab_validation_receipt import (
                application_digest,
                participant_sql_digest,
            )

            deployed = False
            detail = "Your agent and SQL tools match the code in Code Editor, and Aurora runs your SQL."
            failure = "Your deployed agent or SQL tools do not match this run. Next: run make deploy-agent in Code Editor, then ask Alex's question again."
            try:
                status = agentcore_transport.deployed_status()
                if rows and rows.searches:
                    gateway_tools.call_tool(
                        "inspect_retrieval_run",
                        {"run_id": str(rows.searches[0]["search_event_id"])},
                    )
                    with connect() as connection:
                        sql_applied = (
                            applied_sql_digest(connection) == participant_sql_digest()
                        )
                    code_deployed = (
                        status.get("application_sha256") == application_digest()
                    )
                    deployed = code_deployed and sql_applied
                    if code_deployed and not sql_applied:
                        failure = "Aurora runs SQL different from db/sql/09_search_functions.sql in Code Editor. Next: run make db-apply-search-functions, then ask Alex's question again."
            except (RuntimeError, ValueError) as error:
                failure = f"Deployment check failed ({type(error).__name__}). Next: run make deploy-agent in Code Editor, then ask Alex's question again."
            if not deployed:
                detail = failure
            checks.append(
                LabCheck(
                    name="managed_agent_deployed",
                    passed=deployed,
                    falsifier="Runtime or Gateway serves code different from the participant workspace, or the run has no Gateway-readable search.",
                    detail=detail,
                )
            )
        # The turn's own receipts, not new ones: this path issues no retrieval,
        # and reporting them is what makes the verdict replayable afterwards.
        search_event_ids: list[UUID] = (
            [search["search_event_id"] for search in rows.searches] if rows else []
        )
        evidence_ids = sorted(run.resolved_evidence) if run else []
    else:
        checks, search_event_ids = _retrieval_checks(lab_id, mission)
        evidence_ids = []
    if lab_id in FAULT_AT_ENTRY:
        checks.append(
            entry_check(
                lab_id,
                root,
                run_created_at=rows.turn["created_at"] if rows else None,
            )
        )

    finished_at = datetime.now(UTC)
    live_pass = all(check.passed for check in checks)
    return CompletionProofResponse(
        lab_id=lab_id,
        status=(
            "pass" if live_pass and solved and database.state != "stale" else "fail"
        ),
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=round((perf_counter() - started) * 1_000),
        source_state="solved" if solved else "broken",
        database_state=database.state,
        checks=[_served(check) for check in checks],
        evidence=CompletionProofEvidence(
            search_event_ids=search_event_ids,
            agent_run_id=agent_run_id if lab_id == 3 else None,
            evidence_ids=evidence_ids,
        ),
        identity=_identity(),
        release_baseline=_release_baseline(),
        entry_state=_entry(lab_id, root)[0],
        interference=LAB1_UNDER_RANKING_FAULT
        if ranking_fault and not live_pass
        else None,
        saved_completion_at=(
            _saved_completion_at(lab_id, root) if lab_id in {1, 2} else None
        ),
    )
