"""Model-facing Strands tools over the Aurora retrieval contract.

The functions in :mod:`backend.app.agent` are the owning implementations and are
what FastAPI, the Lambda adapter, and the stdio MCP server call. This module is
the *model-facing* surface: the same behavior, reshaped for a model that has to
choose the tool, fill in the arguments, and read the result inside a context
window.

Three rules distinguish it from a direct wrapper:

1. The caller's persona is bound server-side by :func:`start_run` and
   is not a tool parameter. A model that could pass its own persona could escalate
   past the ACL, so it is bound from the request, never from the model.
2. Returns are projected down to the fields a model can act on. The raw
   retrieval row carries 38 keys including UUIDs and legacy aliases; sending
   that for eight rows costs about 4,900 tokens per call and crowds out the
   evidence itself.
3. Failures return a structured payload naming the recovery, instead of raising.
   A raised exception ends the agent loop; a message the model can read lets it
   correct the call it just made.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import UUID

from strands import tool

from agent.registry import TOOLS as _REGISTRY, tools_for
from backend.app.agent import (
    compare_sources_impl,
    decompose_question_impl,
    explain_ranking_impl,
    follow_evidence_links_impl,
    search_evidence_impl,
    synthesize_cited_answer_from_runs_impl,
)
from backend.app.models import DEFAULT_ROLE, EvidenceKind

logger = logging.getLogger(__name__)

# The model-facing tool names, sourced from the single registry (T4) so this module
# cannot advertise a tool the registry does not define. These are the tools exposed
# to the Strands event loop; answer_with_citations is managed-transport-only.
MODEL_TOOLS = [spec.name for spec in tools_for("strands")]

# Per-run state: the caller's persona, the tool-call trace, and the last
# validated synthesis. A ContextVar rather than a module global so concurrent API
# requests in one worker cannot read each other's identity.
#
# It holds one mutable dict that tools mutate in place. Strands executes tools
# through asyncio.to_thread, which runs them in a *copy* of this context, so a
# ContextVar the tool re-assigns is invisible to the caller. Mutating the object
# the variable already points at is what crosses that boundary.
_RUN: ContextVar[dict[str, Any] | None] = ContextVar("workbench_tool_run", default=None)

_EVIDENCE_KINDS = sorted(EvidenceKind.__args__)

_MODEL_ROW_FIELDS = (
    "external_key",
    "title",
    "evidence_kind",
    "source_system",
    "source_revision",
    "cluster_id",
    "incident_id",
    "account_name",
    "severity",
    "environment",
    "occurred_at",
    "snippet",
)


def start_run(role: str | None) -> dict[str, Any]:
    """Begin an agent run: bind its persona and start recording tool calls.

    Args:
        role: The resolved caller persona, or None for the workshop default.

    Returns:
        The live run state. ``trace`` grows and ``answer_of_record`` is filled as
        tools execute, so a caller can read progress while the loop is running.
    """
    run: dict[str, Any] = {
        "role": role or DEFAULT_ROLE,
        "trace": [],
        "answer_of_record": None,
    }
    _RUN.set(run)
    return run


def _run() -> dict[str, Any] | None:
    return _RUN.get()


def _role() -> str:
    run = _run()
    return (run and run["role"]) or DEFAULT_ROLE


def _record(name: str, arguments: dict[str, Any], started: float, **extra: Any) -> None:
    run = _run()
    if run is None:
        return
    trace = run["trace"]
    entry = {
        "sequence": len(trace) + 1,
        "tool": name,
        "arguments": arguments,
        "latency_ms": round((perf_counter() - started) * 1000, 2),
        **extra,
    }
    trace.append(entry)


def _failure(message: str, recovery: str) -> dict[str, Any]:
    """Shape a tool failure the model can read and act on.

    Args:
        message: What went wrong, in terms of the call that was made.
        recovery: The specific next call that would succeed.

    Returns:
        A payload with ``ok`` false, so the model sees a result rather than an
        aborted loop.
    """
    return {"ok": False, "error": message, "recovery": recovery}


def _valid_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _nullable_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return None if normalized.lower() in {"", "null", "none"} else normalized


def _project_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    projected: dict[str, Any] = {"rank": rank}
    for field in _MODEL_ROW_FIELDS:
        value = row.get(field)
        if value is not None:
            projected[field] = value
    tier = row.get("match_tier") or 2
    projected["match"] = "exact_identifier" if tier == 1 else "fused"
    return projected


def decompose_question(question: str) -> dict[str, Any]:
    """Break an incident question into the evidence steps Aurora can answer.

    Call this first. It extracts the identifiers and cluster named in the
    question and returns the subquestions to retrieve, so later searches are
    filtered instead of broad.

    Args:
        question: The user's incident question, verbatim.

    Returns:
        Detected identifiers, inferred filters, and ordered subquestions.
    """
    started = perf_counter()
    plan = decompose_question_impl(question, role=_role())
    result = {
        "identified_keys": plan["identified_keys"],
        "inferred_filters": plan["inferred_filters"],
        "subquestions": [
            {
                "subquestion_id": item["subquestion_id"],
                "text": item["text"],
                "required_kinds": item["required_kinds"],
            }
            for item in plan["subquestions"]
        ],
    }
    _record(
        "decompose_question",
        {"question": question},
        started,
        subquestion_count=len(result["subquestions"]),
    )
    return result


def search_evidence(
    query: str,
    incident_id: str | None = None,
    cluster_id: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Retrieve evidence from Aurora using hybrid retrieval, and persist a receipt.

    Runs all four signals in one SQL statement: exact identifier, full text,
    pgvector semantic, and trigram fuzzy. Exact identifier matches are returned
    as a tier above the fused candidates, so a named identifier cannot be
    outranked. Keep the returned run_id: explain_ranking and
    synthesize_cited_answer both require it.

    Args:
        query: Search text. Include any identifier verbatim, such as CHG-1842.
        incident_id: Restrict to one incident, such as INC-2047.
        cluster_id: Restrict to one database cluster, such as checkout-prod-cluster-01.
        kinds: Restrict to these evidence kinds. Valid values are incident,
            change, support_case, runbook, lock_evidence, commitment, postmortem.
        limit: Rows to return, 1 to 50.

    Returns:
        run_id, the ranked rows with their match tier, and the ranking groups.
    """
    started = perf_counter()
    incident_id = _nullable_filter(incident_id)
    cluster_id = _nullable_filter(cluster_id)
    arguments = {
        "query": query,
        "incident_id": incident_id,
        "cluster_id": cluster_id,
        "kinds": kinds,
        "limit": limit,
    }
    if not query or not query.strip():
        return _failure(
            "query was empty",
            "call search_evidence again with the identifier or symptom text.",
        )
    if kinds:
        unknown = [kind for kind in kinds if kind not in _EVIDENCE_KINDS]
        if unknown:
            return _failure(
                f"unknown evidence kinds {unknown}",
                f"use only these kinds: {', '.join(_EVIDENCE_KINDS)}.",
            )
    try:
        response = search_evidence_impl(
            query,
            kinds=kinds,
            cluster_id=cluster_id,
            incident_id=incident_id,
            role=_role(),
            limit=max(1, min(int(limit), 50)),
        )
    except Exception as error:
        logger.warning("search_evidence failed: %s", error)
        _record("search_evidence", arguments, started, status="failed")
        return _failure(
            f"Aurora retrieval failed: {error}",
            "retry with a narrower query, or drop the filters.",
        )

    rows = response.get("results") or []
    result = {
        "ok": True,
        "run_id": response["run_id"],
        "candidate_count": response.get("candidate_count"),
        "ranking_groups": response.get("match_tiers"),
        "results": [_project_row(row, rank) for rank, row in enumerate(rows, start=1)],
    }
    if not rows:
        result["note"] = (
            "No visible evidence matched. Either the filters exclude it or the "
            f"{_role()} persona cannot see it. Retry without filters before "
            "concluding."
        )
    _record(
        "search_evidence",
        arguments,
        started,
        run_id=response["run_id"],
        result_count=len(rows),
    )
    return result


def follow_evidence_links(
    seed_external_keys: list[str],
    max_depth: int = 2,
) -> dict[str, Any]:
    """Walk declared relationships out from evidence you already retrieved.

    Relationships come from foreign keys, not text similarity, so this is how
    you establish that a change caused an incident or that a runbook was
    superseded. Every hop re-checks the caller's ACL.

    Args:
        seed_external_keys: Keys to start from, such as ["INC-2047"].
        max_depth: Relationship hops to follow, 0 to 8.

    Returns:
        Each reached record with the relation and depth that reached it.
    """
    started = perf_counter()
    arguments = {"seed_external_keys": seed_external_keys, "max_depth": max_depth}
    keys = [key for key in (seed_external_keys or []) if key and key.strip()]
    if not keys:
        return _failure(
            "no seed keys were given",
            "pass external keys from a search_evidence result, such as INC-2047.",
        )
    try:
        response = follow_evidence_links_impl(
            keys,
            role=_role(),
            max_depth=max_depth,
        )
    except Exception as error:
        logger.warning("follow_evidence_links failed: %s", error)
        _record("follow_evidence_links", arguments, started, status="failed")
        return _failure(
            f"traversal failed: {error}",
            "check the seed keys came from a search_evidence result.",
        )

    reached = response.get("reached") or []
    result = {
        "ok": True,
        "seeds": response["seeds"],
        "relationship_count": response.get("relationship_count", 0),
        "reached": [
            {
                "external_key": row.get("external_key"),
                "title": row.get("title"),
                "evidence_kind": row.get("evidence_kind"),
                "depth": row.get("depth"),
                "via_relation": row.get("via_relation"),
                "via_origin": row.get("via_origin"),
                "snippet": row.get("snippet"),
            }
            for row in reached
        ],
    }
    if not reached:
        result["note"] = (
            "No relationships were visible from these seeds. The keys may not "
            f"exist, or the {_role()} persona cannot see them."
        )
    _record(
        "follow_evidence_links",
        arguments,
        started,
        reached_count=len(reached),
    )
    return result


def compare_sources(external_keys: list[str]) -> dict[str, Any]:
    """Compare specific records on revision, timing, scope, and relationships.

    Use this to rule a candidate in or out: it shows whether two records share a
    cluster and incident and whether an explicit relationship joins them.

    Args:
        external_keys: The records to compare, such as ["CHG-1842", "CHG-1838"].

    Returns:
        Each record's scope and revision, plus the relationships between them.
    """
    started = perf_counter()
    arguments = {"external_keys": external_keys}
    keys = [key for key in (external_keys or []) if key and key.strip()]
    if len(keys) < 2:
        return _failure(
            "comparison needs at least two keys",
            "pass two or more external keys, such as CHG-1842 and CHG-1838.",
        )
    try:
        response = compare_sources_impl(keys, role=_role())
    except Exception as error:
        logger.warning("compare_sources failed: %s", error)
        _record("compare_sources", arguments, started, status="failed")
        return _failure(
            f"comparison failed: {error}",
            "check the keys came from a search_evidence result.",
        )

    evidence = response.get("evidence") or []
    missing = sorted(set(keys) - {row.get("external_key") for row in evidence})
    result = {
        "ok": True,
        "evidence": [
            {
                "external_key": row.get("external_key"),
                "evidence_kind": row.get("evidence_kind"),
                "source_system": row.get("source_system"),
                "source_revision": row.get("source_revision"),
                "cluster_id": row.get("cluster_id"),
                "incident_id": row.get("incident_id"),
                "account_name": row.get("account_name"),
                "severity": row.get("severity"),
                "occurred_at": row.get("occurred_at"),
            }
            for row in evidence
        ],
        "relationships": [
            {
                "relation": edge.get("relation"),
                "origin": edge.get("origin"),
                "edge_key": edge.get("edge_key"),
            }
            for edge in (response.get("relationships") or [])
        ],
        "observations": response.get("observations") or [],
    }
    if missing:
        result["not_visible"] = missing
    _record("compare_sources", arguments, started, compared_count=len(evidence))
    return result


def explain_ranking(run_id: str) -> dict[str, Any]:
    """Show why Aurora ordered a retrieval the way it did.

    Reads the persisted receipt for a run_id returned by search_evidence: each
    candidate's per-arm positions, its RRF score, its match tier, and the stage
    timings. Nothing is recomputed and no model is called.

    Args:
        run_id: A run_id from a previous search_evidence call.

    Returns:
        Per-candidate arm positions and scores, plus stage timings.
    """
    started = perf_counter()
    arguments = {"run_id": run_id}
    if not _valid_uuid(run_id):
        return _failure(
            f"{run_id!r} is not a run_id",
            "use the run_id returned by search_evidence, not an evidence key.",
        )
    try:
        response = explain_ranking_impl(run_id, role=_role())
    except ValueError as error:
        _record("explain_ranking", arguments, started, status="not_found")
        return _failure(
            str(error),
            "call search_evidence first and use the run_id it returns.",
        )
    except Exception as error:
        logger.warning("explain_ranking failed: %s", error)
        _record("explain_ranking", arguments, started, status="failed")
        return _failure(
            f"could not read the receipt: {error}",
            "retry once; if it fails again, continue without the explanation.",
        )

    return_value = {
        "ok": True,
        "run_id": run_id,
        "candidates": [
            {
                "result_rank": row.get("result_rank"),
                "external_key": row.get("external_key"),
                "match_tier": row.get("match_tier"),
                "exact_identifier_position": row.get("exact_identifier_position"),
                "text_position": row.get("text_position"),
                "vector_position": row.get("vector_position"),
                "trigram_position": row.get("trigram_position"),
                "rrf_score": row.get("rrf_score"),
                "rerank_score": row.get("rerank_score"),
            }
            for row in (response.get("candidates") or [])
        ],
        "stages": [
            {
                "stage_name": stage.get("stage_name"),
                "duration_ms": stage.get("duration_ms"),
            }
            for stage in (response.get("stages") or [])
        ],
        "score_note": response["score_note"],
    }
    _record("explain_ranking", arguments, started, run_id=run_id)
    return return_value


def synthesize_cited_answer(question: str, run_ids: list[str]) -> dict[str, Any]:
    """Write the final answer from persisted runs, with validated citations.

    This is the last call. Pass every run_id that supports the compound question,
    including a bounded retry used to recover reusable guidance. The function
    reloads the exact visible evidence Aurora persisted, refuses to synthesize if
    a required evidence kind is missing, and validates every citation against the
    stored chunk quote and revision. The answer it produces is delivered to the
    user directly, so you do not need to repeat it.

    Args:
        question: The user's original question, verbatim.
        run_ids: All supporting run_ids returned by search_evidence, in call order.

    Returns:
        The validated answer, its numbered citations, and the synthesis mode.
    """
    started = perf_counter()
    ordered_run_ids = list(dict.fromkeys(run_ids or []))
    arguments = {"question": question, "run_ids": ordered_run_ids}
    invalid = [run_id for run_id in ordered_run_ids if not _valid_uuid(run_id)]
    if not ordered_run_ids or invalid:
        return _failure(
            (
                "no retrieval run_ids were supplied"
                if not ordered_run_ids
                else f"these values are not run_ids: {invalid}"
            ),
            "use every run_id returned by the supporting search_evidence calls.",
        )
    try:
        response = synthesize_cited_answer_from_runs_impl(
            question,
            ordered_run_ids,
            role=_role(),
        )
    except ValueError as error:
        _record("synthesize_cited_answer", arguments, started, status="incomplete")
        return _failure(
            str(error),
            "search only for the missing evidence kinds, relax only scope filters "
            "those reusable kinds do not carry, then retry with every supporting "
            "run_id.",
        )
    except Exception as error:
        logger.warning("synthesize_cited_answer failed: %s", error)
        _record("synthesize_cited_answer", arguments, started, status="failed")
        return _failure(
            f"synthesis failed: {error}",
            "retry once with the same run_id.",
        )

    synthesis = response.get("synthesis") or {}
    result = {
        "ok": True,
        "run_id": response["run_id"],
        "source_run_ids": response["source_run_ids"],
        "required_kinds": response["required_kinds"],
        "answer": response["answer"],
        "citations": [
            {
                "n": citation.get("n"),
                "external_key": citation.get("external_key"),
                "title": citation.get("title"),
                "source_uri": citation.get("source_uri"),
                "source_revision": citation.get("source_revision"),
            }
            for citation in (response.get("citations") or [])
        ],
        "synthesis_mode": synthesis.get("mode"),
        "instruction": (
            "This answer is already returned to the user verbatim. Do not repeat "
            "or rewrite it. Reply with one short sentence stating that the cited "
            "answer is ready, or name any evidence gap you noticed."
        ),
    }
    run = _run()
    if run is not None:
        run["answer_of_record"] = result
    _record(
        "synthesize_cited_answer",
        arguments,
        started,
        run_id=response["run_id"],
        source_run_count=len(response["source_run_ids"]),
        citation_count=len(result["citations"]),
        synthesis_mode=result["synthesis_mode"],
    )
    return result


# The functions above hold the model-facing marshalling (persona binding, row
# projection, failure shaping). Their name, description, and input schema come from
# the single registry (T4), not from their docstrings: the @tool decorator's
# explicit overrides win, so a description the model reads lives in exactly one
# place and G-17 can prove the three transports never disagree.
_TOOL_BODIES = {
    "decompose_question": decompose_question,
    "search_evidence": search_evidence,
    "follow_evidence_links": follow_evidence_links,
    "compare_sources": compare_sources,
    "explain_ranking": explain_ranking,
    "synthesize_cited_answer": synthesize_cited_answer,
}


def _build_tool(name: str):
    """Wrap a marshalling body as a Strands tool, schema-sourced from the registry."""
    spec = _REGISTRY[name]
    return tool(
        _TOOL_BODIES[name],
        name=spec.name,
        description=spec.full_description(),
        inputSchema=spec.strands_input_schema(),
    )


TOOL_FUNCTIONS = [_build_tool(name) for name in MODEL_TOOLS]


def tool_specifications() -> list[dict[str, Any]]:
    """Return the tool schemas exactly as the model receives them.

    Built from the registry via the Strands decorator, so the UI cannot show a
    description or parameter the model was never given.

    Returns:
        One entry per tool with its description and input schema.
    """
    return [dict(function.tool_spec) for function in TOOL_FUNCTIONS]
