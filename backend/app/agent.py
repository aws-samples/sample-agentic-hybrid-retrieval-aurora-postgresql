from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any, Iterator

from .config import get_settings
from .contracts import CONTRACT_VERSION
from .db import get_dict_conn
from .models import AgentAnswerRequest, SearchRequest
from .search import run_hybrid_search
from .verify_sql import receipt_verify_sql

logger = logging.getLogger(__name__)

AGENT_SELECTABLE_TOOLS = [
    "decompose_question",
    "search_evidence",
    "follow_evidence_links",
    "compare_sources",
]
SERVER_TOOLS = [
    "explain_ranking",
    "synthesize_cited_answer",
]


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def agent_metadata() -> dict[str, Any]:
    settings = get_settings()
    return {
        "orchestration": "inspectable tool pipeline",
        "agent_selectable_tools": AGENT_SELECTABLE_TOOLS,
        "server_and_diagnostic_tools": SERVER_TOOLS,
        "model_provider": "Amazon Bedrock",
        "synthesis_model": settings.bedrock_synthesis_model,
        "model_transport": settings.bedrock_model_transport,
        "embedding_model": settings.bedrock_embedding_model,
        "rerank_model": settings.cohere_rerank_model,
        "transport_note": (
            "Global CRIS through Bedrock Converse is the default. The July 2026 "
            "bedrock-mantle Claude endpoint accepts in-region IDs, not CRIS IDs."
        ),
    }


def _first_match(pattern: str, question: str) -> str | None:
    match = re.search(pattern, question, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _anchor_keys(
    incident_id: str,
    kinds: tuple[str, ...],
    role: str,
) -> dict[str, str]:
    """Name the evidence an incident declares a relationship to, per kind.

    The planner writes identifiers into its subquestion text because a generic
    phrase like "the approved runbook" retrieves background runbooks instead of
    this incident's: 15,000 filler documents describe generic remediation, and
    only a named key separates the one that matters. The keys come from the
    declared edges rather than from constants, so the planner works on any
    incident in the corpus.

    Args:
        incident_id: The incident the question named.
        kinds: Evidence kinds to resolve an anchor for.
        role: The caller's persona, threaded from decompose_question_impl. Required
            rather than defaulted: an anchor the caller cannot see must not be
            written into their plan, and a default here silently capped every
            caller at analyst visibility no matter who asked.

    Returns:
        One external key per kind that has a reachable relationship, keyed by
        kind. Kinds with no reachable evidence are absent.
    """
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (walk.evidence_kind)
                  walk.evidence_kind,
                  walk.external_key
                FROM retrieval.traverse_evidence(
                       ARRAY(
                         SELECT evidence_id
                         FROM retrieval.documents
                         WHERE is_current AND incident_id = %(incident_id)s
                       )::uuid[],
                       2
                     ) walk
                WHERE walk.evidence_kind = ANY(%(kinds)s::text[])
                ORDER BY walk.evidence_kind, walk.depth, walk.external_key
                """,
                {
                    "incident_id": incident_id,
                    "kinds": list(kinds),
                },
            )
            return {
                row["evidence_kind"]: row["external_key"]
                for row in cursor.fetchall()
            }


def _planned_subquestions(
    question: str,
    keys: list[str],
    incident_id: str | None,
    role: str,
) -> list[dict[str, Any]]:
    change_keys = [key for key in keys if key.startswith("CHG-")]
    broad_question = bool(
        incident_id
        and (
            len(change_keys) > 1
            or re.search(
                r"\b(?:customer|impact|runbook|recover|prevent|alternative|rule out)\b",
                question,
                flags=re.IGNORECASE,
            )
        )
    )
    if broad_question:
        incident = incident_id
        changes = " or ".join(change_keys[:2]) or "the suspected changes"
        lock_keys = [key for key in keys if key.startswith("LOCK-")]
        runbook_keys = [key for key in keys if key.startswith("RB-")]
        anchors = (
            {}
            if lock_keys and runbook_keys
            else _anchor_keys(incident, ("lock_evidence", "runbook"), role)
        )
        lock_reference = (
            lock_keys[0]
            if lock_keys
            else anchors.get("lock_evidence", "the lock evidence")
        )
        runbook_reference = (
            runbook_keys[0]
            if runbook_keys
            else anchors.get("runbook", "the approved runbook")
        )
        return [
            {
                "subquestion_id": "SQ-1",
                "text": (
                    f"Why did writes hang while reads continued during {incident}, "
                    f"and what did {lock_reference} capture?"
                ),
                "required_kinds": ["incident", "lock_evidence"],
            },
            {
                "subquestion_id": "SQ-2",
                "text": f"Did {changes} cause {incident}?",
                "required_kinds": ["change", "lock_evidence"],
            },
            {
                "subquestion_id": "SQ-3",
                "text": (
                    f"Which customer impact during {incident} is visible to "
                    "the current role?"
                ),
                "required_kinds": ["support_case"],
            },
            {
                "subquestion_id": "SQ-4",
                "text": (
                    f"What evidence rules out the alternative change for {incident}?"
                ),
                "required_kinds": ["change", "lock_evidence"],
            },
            {
                "subquestion_id": "SQ-5",
                "text": (
                    f"How do {lock_reference} and {runbook_reference} support "
                    f"recovery and prevention for {incident}?"
                ),
                "required_kinds": ["lock_evidence", "runbook"],
            },
        ]

    key_kinds = {
        "INC": "incident",
        "CHG": "change",
        "CASE": "support_case",
        "RB": "runbook",
        "LOCK": "lock_evidence",
    }
    required = list(
        dict.fromkeys(
            key_kinds[prefix]
            for key in keys
            for prefix in key_kinds
            if key.startswith(f"{prefix}-")
        )
    )
    lowered = question.lower()
    if "customer" in lowered or "impact" in lowered:
        required.append("support_case")
    if "runbook" in lowered or "safe" in lowered or "recover" in lowered:
        required.append("runbook")
    if "lock" in lowered or "blocked" in lowered or "hang" in lowered:
        required.append("lock_evidence")
    return [
        {
            "subquestion_id": "SQ-1",
            "text": question,
            "required_kinds": list(dict.fromkeys(required)) or ["incident"],
        }
    ]


def decompose_question_impl(
    question: str,
    *,
    role: str = "analyst",
) -> dict[str, Any]:
    """Break an incident question into the evidence steps Aurora can answer.

    Args:
        question: The user's incident question, verbatim.
        role: The caller's persona; bound server-side, never set by the model. It
            reaches the database because the planner resolves anchor identifiers
            from the declared edges, and an anchor the caller cannot retrieve
            would name evidence their own searches then fail to return.

    Returns:
        Detected identifiers, inferred filters, and the ordered subquestions.
    """
    incident_id = _first_match(r"\bINC-[A-Z0-9-]+\b", question)
    cluster_id = _first_match(
        r"\b[a-z][a-z0-9-]*-(?:prod|staging|development)(?:-[a-z0-9]+)*-[0-9]+\b",
        question,
    )
    keys = re.findall(
        r"\b(?:INC|CHG|CASE|RB|LOCK)-[A-Z0-9-]+\b",
        question,
        flags=re.IGNORECASE,
    )
    normalized_keys = list(dict.fromkeys(key.upper() for key in keys))
    subquestions = _planned_subquestions(
        question,
        normalized_keys,
        incident_id.upper() if incident_id else None,
        role,
    )
    return {
        "question": question,
        "identified_keys": normalized_keys,
        "inferred_filters": {
            "incident_id": incident_id.upper() if incident_id else None,
            "cluster_id": cluster_id.lower() if cluster_id else None,
        },
        "subquestions": subquestions,
        "steps": [
            "search_evidence once per subquestion",
            "evaluate deterministic evidence-kind coverage",
            "re-query an uncovered subquestion within the escalation budget",
            "follow_evidence_links",
            "compare_sources",
        ],
    }


def search_evidence_impl(
    query: str,
    *,
    kinds: list[str] | None = None,
    cluster_id: str | None = None,
    incident_id: str | None = None,
    account_name: str | None = None,
    severities: list[str] | None = None,
    environment: str | None = None,
    service_name: str | None = None,
    engine_version: str | None = None,
    aws_region: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    role: str = "analyst",
    limit: int = 8,
    candidate_pool: int = 24,
    rrf_k: int = 60,
    w_text: float = 2.0,
    w_vector: float = 1.0,
    w_trgm: float = 1.0,
    fuzzy_threshold: float = 0.3,
    ef_search: int = 40,
    iterative_scan: str = "strict_order",
    rerank: bool | None = None,
) -> dict[str, Any]:
    return run_hybrid_search(
        SearchRequest(
            query=query,
            kinds=kinds,
            cluster_id=cluster_id,
            incident_id=incident_id,
            account_name=account_name,
            severities=severities,
            environment=environment,
            service_name=service_name,
            engine_version=engine_version,
            aws_region=aws_region,
            start_date=start_date,
            end_date=end_date,
            role=role,
            limit=limit,
            mode="hybrid",
            candidate_pool=candidate_pool,
            rrf_k=rrf_k,
            w_text=w_text,
            w_vector=w_vector,
            w_trgm=w_trgm,
            fuzzy_threshold=fuzzy_threshold,
            ef_search=ef_search,
            iterative_scan=iterative_scan,
            rerank=rerank,
        )
    )


def follow_evidence_links_impl(
    seed_external_keys: list[str],
    *,
    role: str = "analyst",
    max_depth: int = 2,
) -> dict[str, Any]:
    keys = list(dict.fromkeys(key for key in seed_external_keys if key))
    if not keys:
        return {"seeds": [], "reached": [], "relationship_count": 0}
    depth = max(0, min(int(max_depth), 8))
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT evidence_id
                FROM casework.evidence_items
                WHERE external_key = ANY(%s)
                  AND NOT is_deleted
                  AND retrieval.acl_visible(acl)
                ORDER BY external_key
                """,
                (keys,),
            )
            seed_ids = [row["evidence_id"] for row in cursor.fetchall()]
            if not seed_ids:
                return {
                    "seeds": keys,
                    "reached": [],
                    "relationship_count": 0,
                }
            cursor.execute(
                """
                SELECT
                  walk.evidence_id,
                  walk.evidence_kind,
                  walk.external_key,
                  walk.title,
                  walk.depth,
                  walk.path,
                  walk.via_edge_key,
                  walk.via_relation,
                  walk.via_origin,
                  walk.via_confidence,
                  document.document_version_id,
                  chunk.chunk_version_id,
                  document.source_system,
                  document.source_uri,
                  document.source_revision,
                  document.cluster_id,
                  document.incident_id,
                  document.account_name,
                  document.severity,
                  document.environment,
                  document.occurred_at,
                  left(regexp_replace(chunk.chunk_text, '\\s+', ' ', 'g'), 700) AS snippet
                FROM retrieval.traverse_evidence(%s::uuid[], %s) walk
                JOIN retrieval.documents document
                  ON document.evidence_id = walk.evidence_id
                 AND document.is_current
                 AND document.index_state = 'ready'
                JOIN LATERAL (
                  SELECT candidate.chunk_version_id, candidate.chunk_text
                  FROM retrieval.chunks candidate
                  WHERE candidate.document_version_id = document.document_version_id
                  ORDER BY candidate.chunk_ordinal
                  LIMIT 1
                ) chunk ON true
                ORDER BY walk.depth, walk.evidence_kind, walk.external_key
                """,
                (seed_ids, depth),
            )
            reached = cursor.fetchall()
    return {
        "seeds": keys,
        "max_depth": depth,
        "reached": reached,
        "relationship_count": sum(1 for row in reached if row["depth"] > 0),
    }


def compare_sources_impl(
    external_keys: list[str],
    *,
    role: str = "analyst",
) -> dict[str, Any]:
    keys = list(dict.fromkeys(key for key in external_keys if key))
    if not keys:
        return {"evidence": [], "relationships": [], "observations": []}
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  item.evidence_id,
                  item.external_key,
                  item.evidence_kind,
                  item.source_system,
                  item.source_revision,
                  item.source_updated_at,
                  document.cluster_id,
                  document.incident_id,
                  document.account_name,
                  document.severity,
                  document.occurred_at
                FROM casework.evidence_items item
                JOIN retrieval.documents document
                  ON document.evidence_id = item.evidence_id
                 AND document.is_current
                 AND document.index_state = 'ready'
                WHERE item.external_key = ANY(%s)
                  AND NOT item.is_deleted
                  AND retrieval.acl_visible(item.acl)
                ORDER BY document.occurred_at, item.external_key
                """,
                (keys,),
            )
            evidence = cursor.fetchall()
            evidence_ids = [row["evidence_id"] for row in evidence]
            cursor.execute(
                """
                SELECT edge.*
                FROM retrieval.evidence_edges edge
                WHERE edge.from_evidence_id = ANY(%s::uuid[])
                  AND edge.to_evidence_id = ANY(%s::uuid[])
                ORDER BY edge.origin, edge.relation, edge.edge_key
                """,
                (evidence_ids, evidence_ids),
            )
            relationships = cursor.fetchall()

    clusters = sorted(
        {row["cluster_id"] for row in evidence if row.get("cluster_id")}
    )
    incidents = sorted(
        {row["incident_id"] for row in evidence if row.get("incident_id")}
    )
    observations = [
        f"{len(evidence)} visible evidence records came from "
        f"{len({row['source_system'] for row in evidence})} authoritative source types.",
        f"Compared clusters: {', '.join(clusters) if clusters else 'none recorded'}.",
        f"Compared incidents: {', '.join(incidents) if incidents else 'none recorded'}.",
        (
            f"{len(relationships)} explicit relationships were found; "
            "canonical relationships and inferred edges remain distinguishable."
        ),
    ]
    return {
        "evidence": evidence,
        "relationships": relationships,
        "observations": observations,
    }


def _run_role(run_id: str) -> str:
    """Read the persona a retrieval run executed under.

    Replay renders under the run's own identity, not the viewer's, so a receipt
    shows what the run actually saw. proof.retrieval_runs carries no RLS policy,
    so the least-privileged persona can always read this column.

    Args:
        run_id: The run whose stored identity is needed.

    Returns:
        One of db.PERSONAS.

    Raises:
        ValueError: No such run.
    """
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT role FROM proof.retrieval_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ValueError(f"retrieval run {run_id} was not found")
    return row["role"]


def explain_ranking_impl(run_id: str) -> dict[str, Any]:
    """Render a run's receipt under the role that run actually executed under.

    A receipt must show what the run saw, not what the caller can see, so this
    is a replay: the first checkout reads only proof.retrieval_runs (no RLS
    policy, safe under the least-privileged persona) to learn the stored role,
    and the second checkout re-reads the full receipt under that role, because
    v_candidate_receipts and v_answer_receipts are security_invoker joins
    against casework.evidence_items.

    Args:
        run_id: The retrieval run to explain.

    Returns:
        The run, candidates, stages, and answer panels, plus their verify-SQL
        descriptors.

    Raises:
        ValueError: No such run. Raised by _run_role before the second checkout
            opens, so proof.v_run_receipts is never queried for a run_id that
            does not exist: proof.retrieval_runs carries no RLS, and
            v_run_receipts LEFT JOINs candidates and GROUPs BY run_id, so every
            row in retrieval_runs yields exactly one receipt row. There is no
            second not-found case to guard.
    """
    role = _run_role(run_id)
    verify = receipt_verify_sql(run_id, role)
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(verify["run"]["statement"], verify["run"]["binds"])
            run = cursor.fetchone()
            cursor.execute(
                verify["candidates"]["statement"],
                verify["candidates"]["binds"],
            )
            candidates = cursor.fetchall()
            cursor.execute(
                verify["stages"]["statement"],
                verify["stages"]["binds"],
            )
            stages = cursor.fetchall()
            cursor.execute(verify["answer"]["statement"], verify["answer"]["binds"])
            answer = cursor.fetchone()
    return {
        "run": run,
        "candidates": candidates,
        "stages": stages,
        "answer": answer,
        "score_note": (
            "Raw arm scores diagnose each retriever. final_score is weighted RRF; "
            "rerank_score is a separate post-fusion ordering signal. None is a probability."
        ),
        "_verify_sql": verify,
    }


_EXTRACTIVE_KIND_ORDER = (
    "incident",
    "change",
    "lock_evidence",
    "support_case",
    "runbook",
)
def _row_relations(row: dict[str, Any]) -> list[str]:
    relations = []
    if row.get("via_relation"):
        relations.append(str(row["via_relation"]))
    for relationship in row.get("relationships") or []:
        relation = relationship.get("relation")
        if relation:
            relations.append(str(relation))
    return list(dict.fromkeys(relations))


def _preferred_relation(row: dict[str, Any]) -> str | None:
    priorities = {
        "change": ("change_confirmed", "change_ruled_out"),
        "lock_evidence": ("observed_during",),
        "support_case": (
            "support_case_affected",
            "support_case_not_affected",
        ),
        "runbook": ("runbook_used",),
    }
    relations = _row_relations(row)
    for relation in priorities.get(str(row.get("evidence_kind")), ()):
        if relation in relations:
            return relation
    return relations[0] if relations else None


def _is_negative_evidence(row: dict[str, Any]) -> bool:
    kind = row.get("evidence_kind")
    relations = set(_row_relations(row))
    return (
        kind == "change"
        and "change_ruled_out" in relations
        or kind == "support_case"
        and "support_case_not_affected" in relations
    )


def _excerpt(row: dict[str, Any], max_chars: int = 420) -> str:
    normalized = " ".join(str(row.get("snippet") or "").split())
    normalized = normalized.replace("[", "(").replace("]", ")")
    if len(normalized) <= max_chars:
        return normalized
    bounded = normalized[: max_chars + 1]
    if " " in bounded:
        bounded = bounded.rsplit(" ", 1)[0]
    return f"{bounded.rstrip(' ,;:')}..."


def _extractive_answer(
    question: str,
    evidence: list[dict[str, Any]],
) -> tuple[str, list[int]]:
    if not evidence:
        return (
            "No visible evidence was retrieved, so the question cannot be answered.",
            [],
        )

    named_keys = set(
        key.upper()
        for key in re.findall(
            r"\b(?:INC|CHG|CASE|RB|LOCK)-[A-Z0-9-]+\b",
            question,
            flags=re.IGNORECASE,
        )
    )
    indexed = list(enumerate(evidence, start=1))
    selected: list[tuple[int, dict[str, Any]]] = []
    selected_numbers: set[int] = set()

    for kind in _EXTRACTIVE_KIND_ORDER:
        candidates = [
            item
            for item in indexed
            if item[0] not in selected_numbers
            and item[1].get("evidence_kind") == kind
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (
                str(item[1].get("external_key") or "").upper() not in named_keys,
                _is_negative_evidence(item[1]),
                item[0],
            )
        )
        number, row = candidates[0]
        selected.append((number, row))
        selected_numbers.add(number)

    for number, row in indexed:
        if len(selected) >= 5:
            break
        if number in selected_numbers or _is_negative_evidence(row):
            continue
        selected.append((number, row))
        selected_numbers.add(number)

    labels = {
        "incident": "Incident evidence",
        "change": "Change evidence",
        "lock_evidence": "Observed lock evidence",
        "support_case": "Visible customer evidence",
        "runbook": "Safe-fix guidance",
    }
    sentences = []
    for number, row in selected:
        kind = str(row.get("evidence_kind") or "")
        label = labels.get(kind, "Retrieved evidence")
        account = (
            f" for {row['account_name']}"
            if kind == "support_case" and row.get("account_name")
            else ""
        )
        preferred_relation = _preferred_relation(row)
        relation = (
            f" ({preferred_relation.replace('_', ' ')})"
            if preferred_relation
            else ""
        )
        sentences.append(
            f"{label}{account}{relation}, {row['external_key']}: "
            f"{_excerpt(row)} [{number}]"
        )
    return " ".join(sentences), [number for number, _ in selected]


def _cited_numbers(answer: str, evidence_count: int) -> list[int]:
    numbers = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    unique = list(dict.fromkeys(numbers))
    if not unique or any(number < 1 or number > evidence_count for number in unique):
        raise ValueError("synthesis did not return valid evidence citation numbers")
    return unique


def _persist_answer(
    run_id: str,
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
    citation_numbers: list[int],
    synthesis: dict[str, Any],
    agent_run_id: str | None = None,
    *,
    role: str = "analyst",
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    with get_dict_conn(role) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proof.agent_answers(
                      run_id,
                      agent_run_id,
                      question,
                      answer_text,
                      synthesis_mode,
                      validation_status,
                      model_id,
                      model_transport,
                      input_tokens,
                      output_tokens
                    )
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                      agent_run_id = EXCLUDED.agent_run_id,
                      question = EXCLUDED.question,
                      answer_text = EXCLUDED.answer_text,
                      synthesis_mode = EXCLUDED.synthesis_mode,
                      validation_status = 'pending',
                      model_id = EXCLUDED.model_id,
                      model_transport = EXCLUDED.model_transport,
                      input_tokens = EXCLUDED.input_tokens,
                      output_tokens = EXCLUDED.output_tokens,
                      created_at = now()
                    """,
                    (
                        run_id,
                        agent_run_id,
                        question,
                        answer,
                        synthesis["mode"],
                        synthesis.get("model"),
                        synthesis.get("transport"),
                        synthesis.get("usage", {}).get("input_tokens"),
                        synthesis.get("usage", {}).get("output_tokens"),
                    ),
                )
                cursor.execute(
                    "DELETE FROM proof.answer_citations WHERE run_id = %s",
                    (run_id,),
                )
                cursor.execute(
                    """
                    SELECT
                      requested.citation_number,
                      document.evidence_id,
                      document.document_version_id,
                      chunk.chunk_version_id,
                      document.source_uri,
                      document.source_revision,
                      left(chunk.chunk_text, 500) AS quote_text
                    FROM unnest(
                           %(citation_numbers)s::integer[],
                           %(document_version_ids)s::uuid[],
                           %(chunk_version_ids)s::uuid[],
                           %(evidence_ids)s::uuid[]
                         ) AS requested(
                           citation_number,
                           document_version_id,
                           chunk_version_id,
                           evidence_id
                         )
                    JOIN retrieval.documents document
                      ON document.document_version_id
                         = requested.document_version_id
                     AND document.evidence_id = requested.evidence_id
                    JOIN retrieval.chunks chunk
                      ON chunk.document_version_id
                         = document.document_version_id
                     AND chunk.chunk_version_id = requested.chunk_version_id
                    """,
                    {
                        "citation_numbers": citation_numbers,
                        # Evidence reaches here from several retrieval hops, so
                        # the ids arrive as a mix of UUID and str. A bound array
                        # has to be one type, hence the explicit str().
                        "document_version_ids": [
                            str(evidence[number - 1]["document_version_id"])
                            for number in citation_numbers
                        ],
                        "chunk_version_ids": [
                            str(evidence[number - 1]["chunk_version_id"])
                            for number in citation_numbers
                        ],
                        "evidence_ids": [
                            str(evidence[number - 1]["evidence_id"])
                            for number in citation_numbers
                        ],
                    },
                )
                resolved = {
                    source["citation_number"]: source
                    for source in cursor.fetchall()
                }
                unresolved = [
                    number for number in citation_numbers if number not in resolved
                ]
                if unresolved:
                    raise ValueError(
                        f"citation {unresolved[0]} does not resolve to indexed evidence"
                    )
                cursor.executemany(
                    """
                    INSERT INTO proof.answer_citations(
                      run_id,
                      citation_number,
                      evidence_id,
                      document_version_id,
                      chunk_version_id,
                      source_uri,
                      source_revision,
                      quote_text,
                      claim
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
                    """,
                    [
                        (
                            run_id,
                            number,
                            resolved[number]["evidence_id"],
                            resolved[number]["document_version_id"],
                            resolved[number]["chunk_version_id"],
                            resolved[number]["source_uri"],
                            resolved[number]["source_revision"],
                            resolved[number]["quote_text"],
                        )
                        for number in citation_numbers
                    ],
                )
                for citation_number in citation_numbers:
                    row = evidence[citation_number - 1]
                    source = resolved[citation_number]
                    citations.append(
                        {
                            "n": citation_number,
                            "evidence_id": str(source["evidence_id"]),
                            "document_version_id": str(source["document_version_id"]),
                            "chunk_version_id": str(source["chunk_version_id"]),
                            "external_key": row["external_key"],
                            "title": row["title"],
                            "source_uri": source["source_uri"],
                            "source_revision": source["source_revision"],
                            "quote_text": source["quote_text"],
                        }
                    )
                cursor.execute(
                    "SELECT * FROM proof.validate_answer_citations(%s)",
                    (run_id,),
                )
                validation = cursor.fetchall()
                invalid = [row for row in validation if not row["is_valid"]]
                if invalid:
                    cursor.execute(
                        """
                        UPDATE proof.agent_answers
                        SET validation_status = 'failed'
                        WHERE run_id = %s
                        """,
                        (run_id,),
                    )
                    raise ValueError(f"citation validation failed: {invalid}")
                cursor.execute(
                    """
                    UPDATE proof.agent_answers
                    SET validation_status = 'valid'
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
    return citations


def synthesize_cited_answer_impl(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    agent_run_id: str | None = None,
    required_kinds: list[str] | None = None,
    role: str = "analyst",
) -> dict[str, Any]:
    try:
        from .synthesis import synthesize_live

        synthesis = synthesize_live(
            question,
            evidence,
            required_kinds=required_kinds,
        )
        answer = synthesis["answer"]
        numbers = _cited_numbers(answer, min(8, len(evidence)))
        missing_cited_kinds = sorted(
            set(required_kinds or [])
            - {
                str(evidence[number - 1].get("evidence_kind"))
                for number in numbers
            }
        )
        if missing_cited_kinds:
            raise ValueError(
                "synthesis omitted required evidence kinds: "
                + ", ".join(missing_cited_kinds)
            )
        synthesis["mode"] = "bedrock"
    except Exception as error:
        logger.warning("Model synthesis unavailable; using extractive evidence: %s", error)
        answer, numbers = _extractive_answer(question, evidence)
        missing_cited_kinds = sorted(
            set(required_kinds or [])
            - {
                str(evidence[number - 1].get("evidence_kind"))
                for number in numbers
            }
        )
        if missing_cited_kinds:
            raise ValueError(
                "available evidence cannot cite required kinds: "
                + ", ".join(missing_cited_kinds)
            ) from error
        synthesis = {
            "mode": "extractive_fallback",
            "model": None,
            "transport": None,
            "usage": {},
            "fallback_reason": str(error),
        }

    citations = (
        _persist_answer(
            run_id,
            question,
            answer,
            evidence,
            numbers,
            synthesis,
            agent_run_id=agent_run_id,
            role=role,
        )
        if run_id
        else [
            {
                "n": number,
                "evidence_id": str(evidence[number - 1]["evidence_id"]),
                "external_key": evidence[number - 1]["external_key"],
                "title": evidence[number - 1]["title"],
                "source_uri": evidence[number - 1]["source_uri"],
                "source_revision": evidence[number - 1]["source_revision"],
            }
            for number in numbers
        ]
    )
    return {
        "answer": answer,
        "citations": citations,
        "synthesis": synthesis,
    }


def _evidence_for_run(run_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Reload a run's persisted candidates under the role that run executed under.

    RLS is FORCE-enabled on retrieval.documents and retrieval.chunks, so a
    connection checked out under the wrong role would lose restricted rows to
    the policy even if this query's own predicate said they were visible. This
    is why the role has to be read first, in its own least-privileged checkout,
    then used to open the checkout that actually reads the documents and chunks.

    Args:
        run_id: The persisted retrieval run to reload.
        limit: Rows to return, bounded to the receipt's own 8-row cap.

    Returns:
        The run's candidate rows, still filtered by the run's own role.

    Raises:
        ValueError: The run does not exist, or that role sees none of its rows.
    """
    bounded_limit = max(1, min(int(limit), 8))
    role = _run_role(run_id)
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  candidate.evidence_id,
                  candidate.document_version_id,
                  candidate.chunk_version_id,
                  document.evidence_kind,
                  document.external_key,
                  document.title,
                  document.source_system,
                  document.source_uri,
                  document.source_revision,
                  document.cluster_id,
                  document.incident_id,
                  document.account_name,
                  document.severity,
                  document.environment,
                  document.occurred_at,
                  left(
                    regexp_replace(chunk.chunk_text, '\\s+', ' ', 'g'),
                    700
                  ) AS snippet
                FROM proof.retrieval_candidates candidate
                JOIN retrieval.documents document
                  ON document.document_version_id = candidate.document_version_id
                 AND document.evidence_id = candidate.evidence_id
                JOIN retrieval.chunks chunk
                  ON chunk.chunk_version_id = candidate.chunk_version_id
                 AND chunk.document_version_id = document.document_version_id
                WHERE candidate.run_id = %s
                  AND retrieval.acl_visible(document.acl)
                ORDER BY candidate.result_rank
                LIMIT %s
                """,
                (run_id, bounded_limit),
            )
            evidence = cursor.fetchall()
    if not evidence:
        raise ValueError(f"retrieval run {run_id} has no visible persisted evidence")
    return evidence


def synthesize_cited_answer_from_run_impl(
    question: str,
    run_id: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    evidence = _evidence_for_run(run_id, limit=limit)
    result = synthesize_cited_answer_impl(
        question,
        evidence,
        run_id=run_id,
        role=_run_role(run_id),
    )
    return {"run_id": run_id, **result}


def synthesize_cited_answer_from_runs_impl(
    question: str,
    run_ids: list[str],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Synthesize from multiple persisted retrievals without weakening their ACLs.

    Compound incident questions often need a scoped incident retrieval plus an
    unscoped retrieval for reusable guidance. Each run has already applied the
    caller's role before persisting candidates. This function interleaves
    those visible candidates, guarantees one row for every required evidence
    kind, and persists the answer against the first run as its receipt anchor.
    """
    ordered_run_ids = list(dict.fromkeys(str(run_id) for run_id in run_ids))
    if not ordered_run_ids:
        raise ValueError("at least one retrieval run_id is required")

    bounded_limit = max(1, min(int(limit), 8))
    evidence_by_run = [
        _evidence_for_run(run_id, limit=bounded_limit)
        for run_id in ordered_run_ids
    ]
    interleaved: list[dict[str, Any]] = []
    for rank in range(max(len(rows) for rows in evidence_by_run)):
        for rows in evidence_by_run:
            if rank < len(rows):
                interleaved.append(rows[rank])

    plan = decompose_question_impl(question)
    required_kinds = list(
        dict.fromkeys(
            kind
            for subquestion in plan["subquestions"]
            for kind in subquestion["required_kinds"]
        )
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def append(row: dict[str, Any]) -> None:
        evidence_id = str(row["evidence_id"])
        if evidence_id in selected_ids or len(selected) >= bounded_limit:
            return
        selected_ids.add(evidence_id)
        selected.append(row)

    for kind in required_kinds:
        row = next(
            (
                candidate
                for candidate in interleaved
                if candidate.get("evidence_kind") == kind
            ),
            None,
        )
        if row:
            append(row)

    named_keys = set(plan["identified_keys"])
    for row in interleaved:
        if row.get("external_key") in named_keys:
            append(row)
    for row in interleaved:
        append(row)

    present_kinds = {str(row.get("evidence_kind")) for row in selected}
    missing_kinds = [kind for kind in required_kinds if kind not in present_kinds]
    if missing_kinds:
        raise ValueError(
            "persisted retrievals are missing required evidence kinds: "
            + ", ".join(missing_kinds)
        )

    result = synthesize_cited_answer_impl(
        question,
        selected,
        run_id=ordered_run_ids[0],
        required_kinds=required_kinds,
        role=_run_role(ordered_run_ids[0]),
    )
    return {
        "run_id": ordered_run_ids[0],
        "source_run_ids": ordered_run_ids,
        "required_kinds": required_kinds,
        **result,
    }


def _merge_evidence(
    retrieved: list[dict[str, Any]],
    reached: list[dict[str, Any]],
    *,
    named_keys: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    reached_by_id = {
        str(row["evidence_id"]): row
        for row in reached
        if row.get("depth", 0) > 0
    }
    named = [
        row for row in retrieved if row["external_key"] in set(named_keys)
    ]
    linked = [row for row in reached if row.get("depth", 0) > 0]
    for row in [*named, *retrieved, *linked]:
        evidence_id = str(row["evidence_id"])
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        enriched = dict(row)
        linked_row = reached_by_id.get(evidence_id)
        if linked_row:
            for key in (
                "depth",
                "path",
                "via_edge_key",
                "via_relation",
                "via_origin",
                "via_confidence",
            ):
                if linked_row.get(key) is not None:
                    enriched[key] = linked_row[key]
        merged.append(enriched)
        if len(merged) >= limit:
            break
    return merged


def _attach_relationships(
    evidence: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched = [dict(row) for row in evidence]
    by_id = {str(row["evidence_id"]): row for row in enriched}
    for edge in relationships:
        from_id = str(edge["from_evidence_id"])
        to_id = str(edge["to_evidence_id"])
        from_row = by_id.get(from_id)
        to_row = by_id.get(to_id)
        if not from_row or not to_row:
            continue
        metadata = edge.get("metadata") or {}
        common = {
            "relation": edge["relation"],
            "origin": edge["origin"],
            "confidence": edge["confidence"],
            "rationale": metadata.get("rationale"),
        }
        from_row.setdefault("relationships", []).append(
            {
                **common,
                "direction": "outbound",
                "other_external_key": to_row["external_key"],
            }
        )
        to_row.setdefault("relationships", []).append(
            {
                **common,
                "direction": "inbound",
                "other_external_key": from_row["external_key"],
            }
        )
    return enriched


def _append_agent_stage(
    run_id: str,
    name: str,
    duration_ms: int,
    details: dict[str, Any],
    *,
    role: str = "analyst",
) -> None:
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.run_stages(
                  run_id, stage_ordinal, stage_name, duration_ms, details
                )
                SELECT
                  %s,
                  coalesce(max(stage_ordinal), 0) + 1,
                  %s,
                  %s,
                  %s::jsonb
                FROM proof.run_stages
                WHERE run_id = %s
                """,
                (run_id, name, duration_ms, _json(details), run_id),
            )


def _agent_filters(
    request: AgentAnswerRequest,
    inferred: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cluster_id": request.cluster_id or inferred.get("cluster_id"),
        "incident_id": request.incident_id or inferred.get("incident_id"),
        "account_name": request.account_name,
        "severities": request.severities,
        "environment": request.environment,
        "service_name": request.service_name,
        "engine_version": request.engine_version,
        "aws_region": request.aws_region,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }


def _agent_controls(request: AgentAnswerRequest) -> dict[str, Any]:
    return {
        "mode": "hybrid",
        "candidate_pool": request.candidate_pool,
        "rrf_k": request.rrf_k,
        "w_text": request.w_text,
        "w_vector": request.w_vector,
        "w_trgm": request.w_trgm,
        "fuzzy_threshold": request.fuzzy_threshold,
        "ef_search": request.ef_search,
        "iterative_scan": request.iterative_scan,
        "rerank": request.rerank,
    }


def _start_agent_run(
    request: AgentAnswerRequest,
    plan: dict[str, Any],
    filters: dict[str, Any],
    controls: dict[str, Any],
) -> str:
    with get_dict_conn(request.role) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proof.agent_runs(
                      question,
                      role,
                      filters_initial,
                      controls_initial,
                      max_tool_calls,
                      max_escalations,
                      tool_calls_spent,
                      status,
                      contract_version
                    )
                    VALUES (
                      %s, %s, %s::jsonb, %s::jsonb,
                      %s, %s, 1, 'running', %s
                    )
                    RETURNING agent_run_id
                    """,
                    (
                        request.question,
                        request.role,
                        _json(filters),
                        _json(controls),
                        request.max_tool_calls,
                        request.max_escalations,
                        CONTRACT_VERSION,
                    ),
                )
                agent_run_id = str(cursor.fetchone()["agent_run_id"])
                cursor.executemany(
                    """
                    INSERT INTO proof.agent_subquestions(
                      agent_run_id,
                      subquestion_id,
                      ordinal,
                      subquestion_text,
                      required_kinds,
                      coverage_top_n,
                      missing_kinds
                    )
                    VALUES (%s, %s, %s, %s, %s::text[], %s, %s::text[])
                    """,
                    [
                        (
                            agent_run_id,
                            subquestion["subquestion_id"],
                            ordinal,
                            subquestion["text"],
                            subquestion["required_kinds"],
                            request.limit,
                            subquestion["required_kinds"],
                        )
                        for ordinal, subquestion in enumerate(
                            plan["subquestions"],
                            start=1,
                        )
                    ],
                )
    return agent_run_id


def _spend_agent_budget(
    agent_run_id: str,
    *,
    tool_calls: int = 0,
    escalations: int = 0,
    role: str = "analyst",
) -> bool:
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE proof.agent_runs
                SET tool_calls_spent = tool_calls_spent + %s,
                    escalations_spent = escalations_spent + %s
                WHERE agent_run_id = %s
                  AND tool_calls_spent + %s <= max_tool_calls
                  AND escalations_spent + %s <= max_escalations
                RETURNING agent_run_id
                """,
                (
                    tool_calls,
                    escalations,
                    agent_run_id,
                    tool_calls,
                    escalations,
                ),
            )
            return cursor.fetchone() is not None


def _evaluate_coverage(
    run_id: str,
    required_kinds: list[str],
    *,
    top_n: int,
    role: str = "analyst",
) -> dict[str, Any]:
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM proof.evaluate_subquestion_coverage(
                  %s, %s::text[], %s
                )
                """,
                (run_id, required_kinds, top_n),
            )
            return cursor.fetchone()


def _persist_agent_retrieval(
    agent_run_id: str,
    subquestion: dict[str, Any],
    *,
    run_id: str,
    attempt: int,
    coverage: dict[str, Any],
    role: str = "analyst",
) -> None:
    with get_dict_conn(role) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                if attempt > 1:
                    cursor.execute(
                        """
                        UPDATE proof.agent_retrievals
                        SET superseded_by = %s
                        WHERE agent_run_id = %s
                          AND subquestion_id = %s
                          AND attempt = %s
                        """,
                        (
                            attempt,
                            agent_run_id,
                            subquestion["subquestion_id"],
                            attempt - 1,
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO proof.agent_retrievals(
                      agent_run_id,
                      subquestion_id,
                      attempt,
                      run_id
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        agent_run_id,
                        subquestion["subquestion_id"],
                        attempt,
                        run_id,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE proof.agent_subquestions
                    SET covered = %s,
                        covering_evidence_ids = %s::jsonb,
                        missing_kinds = %s::text[],
                        attempts = %s
                    WHERE agent_run_id = %s
                      AND subquestion_id = %s
                    """,
                    (
                        coverage["covered"],
                        _json(coverage["covering_evidence_ids"]),
                        coverage["missing_kinds"],
                        attempt,
                        agent_run_id,
                        subquestion["subquestion_id"],
                    ),
                )


def _persist_escalation(
    agent_run_id: str,
    subquestion: dict[str, Any],
    *,
    attempt: int,
    initial_coverage: dict[str, Any],
    changed: dict[str, Any],
    rationale: str,
    outcome: str,
    role: str = "analyst",
) -> None:
    reason = (
        "zero_candidates"
        if initial_coverage["considered"] == 0
        else "missing_required_kind"
    )
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.agent_escalations(
                  agent_run_id,
                  subquestion_id,
                  attempt,
                  reason,
                  missing_kinds,
                  changed,
                  rationale,
                  outcome
                )
                VALUES (%s, %s, %s, %s, %s::text[], %s::jsonb, %s, %s)
                """,
                (
                    agent_run_id,
                    subquestion["subquestion_id"],
                    attempt,
                    reason,
                    initial_coverage["missing_kinds"],
                    _json(changed),
                    rationale,
                    outcome,
                ),
            )


def _finish_agent_run(
    agent_run_id: str,
    status: str,
    *,
    error: str | None = None,
    role: str = "analyst",
) -> None:
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE proof.agent_runs
                SET status = %s,
                    ended_at = now(),
                    error = %s
                WHERE agent_run_id = %s
                """,
                (status, error[:4000] if error else None, agent_run_id),
            )


def _retrieval_controls(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": row["retrieval_mode"],
        "candidate_pool": row["candidate_pool"],
        "rrf_k": row["rrf_k"],
        "w_text": float(row["text_weight"]),
        "w_vector": float(row["vector_weight"]),
        "w_trgm": float(row["fuzzy_weight"]),
        "fuzzy_threshold": float(row["fuzzy_threshold"]),
        "ef_search": row["hnsw_ef_search"],
        "iterative_scan": row["hnsw_iterative_scan"],
        "rerank": bool(row["rerank_model"]),
    }


def get_agent_run_impl(agent_run_id: str) -> dict[str, Any]:
    """Render an agent run's receipt under the role that run executed under.

    Same replay shape as explain_ranking_impl: proof.agent_runs has no RLS
    policy, so the first checkout under the least-privileged persona is safe,
    but the second checkout has to run as the run's own role because it joins
    casework.evidence_items (via proof.evaluate_subquestion_coverage and the
    now-security_invoker proof.v_answer_receipts).

    Args:
        agent_run_id: The agent run to render.

    Returns:
        The agent run's subquestions, retrievals, escalations, and any
        finished cited answer.

    Raises:
        ValueError: No such agent run.
    """
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT role FROM proof.agent_runs WHERE agent_run_id = %s",
                (agent_run_id,),
            )
            role_row = cursor.fetchone()
    if not role_row:
        raise ValueError(f"agent run {agent_run_id} was not found")
    with get_dict_conn(role_row["role"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM proof.agent_runs WHERE agent_run_id = %s",
                (agent_run_id,),
            )
            agent_run = cursor.fetchone()
            if not agent_run:
                raise ValueError(f"agent run {agent_run_id} was not found")
            cursor.execute(
                """
                SELECT *
                FROM proof.agent_subquestions
                WHERE agent_run_id = %s
                ORDER BY ordinal
                """,
                (agent_run_id,),
            )
            subquestions = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                  retrieval.agent_run_id,
                  retrieval.subquestion_id,
                  retrieval.attempt,
                  retrieval.run_id,
                  retrieval.superseded_by,
                  run.retrieval_mode,
                  run.filters,
                  run.rrf_k,
                  run.text_weight,
                  run.vector_weight,
                  run.fuzzy_weight,
                  run.fuzzy_threshold,
                  run.candidate_pool,
                  run.hnsw_ef_search,
                  run.hnsw_iterative_scan,
                  run.rerank_model,
                  coverage.covered,
                  coverage.missing_kinds,
                  coverage.covering_evidence_ids,
                  coverage.considered
                FROM proof.agent_retrievals retrieval
                JOIN proof.retrieval_runs run ON run.run_id = retrieval.run_id
                JOIN proof.agent_subquestions subquestion
                  ON subquestion.agent_run_id = retrieval.agent_run_id
                 AND subquestion.subquestion_id = retrieval.subquestion_id
                CROSS JOIN LATERAL proof.evaluate_subquestion_coverage(
                  retrieval.run_id,
                  subquestion.required_kinds,
                  subquestion.coverage_top_n
                ) coverage
                WHERE retrieval.agent_run_id = %s
                ORDER BY subquestion.ordinal, retrieval.attempt
                """,
                (agent_run_id,),
            )
            retrievals = cursor.fetchall()
            cursor.execute(
                """
                SELECT *
                FROM proof.agent_escalations
                WHERE agent_run_id = %s
                ORDER BY created_at, subquestion_id, attempt
                """,
                (agent_run_id,),
            )
            escalations = cursor.fetchall()
            cursor.execute(
                """
                SELECT receipt.*, answer.validation_status
                FROM proof.agent_answers answer
                JOIN proof.v_answer_receipts receipt
                  ON receipt.run_id = answer.run_id
                WHERE answer.agent_run_id = %s
                """,
                (agent_run_id,),
            )
            answer = cursor.fetchone()

    attempts_by_subquestion: dict[str, list[dict[str, Any]]] = {}
    run_id_by_attempt = {
        (row["subquestion_id"], row["attempt"]): str(row["run_id"])
        for row in retrievals
    }
    for row in retrievals:
        coverage = {
            "covered": row["covered"],
            "missing_kinds": row["missing_kinds"],
            "covering_evidence_ids": row["covering_evidence_ids"],
            "considered": row["considered"],
        }
        attempt = {
            "run_id": str(row["run_id"]),
            "attempt": row["attempt"],
            "filters": row["filters"],
            "controls": _retrieval_controls(row),
            "coverage": coverage,
        }
        if row["superseded_by"]:
            attempt["superseded_by"] = run_id_by_attempt.get(
                (row["subquestion_id"], row["superseded_by"])
            )
        attempts_by_subquestion.setdefault(row["subquestion_id"], []).append(attempt)

    rendered_subquestions = []
    for row in subquestions:
        attempts = attempts_by_subquestion.get(row["subquestion_id"], [])
        rendered_subquestions.append(
            {
                "subquestion_id": row["subquestion_id"],
                "text": row["subquestion_text"],
                "required_kinds": row["required_kinds"],
                "attempts": row["attempts"],
                "runs": attempts,
                "final_coverage": {
                    "covered": row["covered"],
                    "missing_kinds": row["missing_kinds"],
                    "covering_evidence_ids": row["covering_evidence_ids"],
                    "considered": (
                        attempts[-1]["coverage"]["considered"] if attempts else 0
                    ),
                },
            }
        )

    rendered_escalations = [
        {
            "subquestion_id": row["subquestion_id"],
            "attempt": row["attempt"],
            "reason": row["reason"],
            "missing_kinds": row["missing_kinds"],
            "changed": row["changed"],
            "rationale": row["rationale"],
            "outcome": row["outcome"],
        }
        for row in escalations
    ]
    response = {
        "agent_run_id": str(agent_run["agent_run_id"]),
        "question": agent_run["question"],
        "role": agent_run["role"],
        "filters_initial": agent_run["filters_initial"],
        "controls_initial": agent_run["controls_initial"],
        "budget": {
            "max_tool_calls": agent_run["max_tool_calls"],
            "max_escalations": agent_run["max_escalations"],
        },
        "tool_calls_spent": agent_run["tool_calls_spent"],
        "escalations_spent": agent_run["escalations_spent"],
        "status": agent_run["status"],
        "subquestions": rendered_subquestions,
        "escalations": rendered_escalations,
        "retrievals": [
            {
                "run_id": str(row["run_id"]),
                "subquestion_id": row["subquestion_id"],
                "attempt": row["attempt"],
            }
            for row in retrievals
        ],
        "started_at": agent_run["started_at"],
        "ended_at": agent_run["ended_at"],
        "error": agent_run["error"],
    }
    if answer:
        response.update(
            {
                "run_id": str(answer["run_id"]),
                "answer": answer["answer_text"],
                "citations": answer["citations"],
                "synthesis": {
                    "mode": answer["synthesis_mode"],
                    "model": answer["model_id"],
                    "transport": answer["model_transport"],
                },
                "validation_status": answer["validation_status"],
            }
        )
    else:
        response.update({"answer": "", "citations": [], "synthesis": None})
    return response


def get_agent_coverage_impl(agent_run_id: str) -> dict[str, Any]:
    run = get_agent_run_impl(agent_run_id)
    subquestions = [
        {
            "subquestion_id": row["subquestion_id"],
            "text": row["text"],
            "required_kinds": row["required_kinds"],
            "attempts": row["attempts"],
            "run_ids": [attempt["run_id"] for attempt in row["runs"]],
            "final_coverage": row["final_coverage"],
        }
        for row in run["subquestions"]
    ]
    return {
        "agent_run_id": run["agent_run_id"],
        "status": run["status"],
        "subquestion_count": len(subquestions),
        "covered_count": sum(
            1 for row in subquestions if row["final_coverage"]["covered"]
        ),
        "subquestions": subquestions,
    }


_SCOPE_FILTERS = ("cluster_id", "incident_id", "service_name", "account_name")


def _unscoped_filters(
    missing_kinds: list[str],
    filters: dict[str, Any],
    role: str = "analyst",
) -> list[str]:
    """Name the active scope filters that no document of a missing kind carries.

    A runbook is a reusable procedure, so it has no incident or cluster. Filtering
    an incident's evidence by incident then excludes the runbook before fusion, and
    widening the candidate pool cannot recover it. Aurora is asked which columns are
    unpopulated for the kinds still missing rather than hardcoding which kinds those
    are, so a corpus that starts scoping runbooks needs no code change here.

    Args:
        missing_kinds: Evidence kinds the first retrieval did not cover.
        filters: The filters that retrieval ran with.
        role: The persona to check out under; the request's role in the agent
            loop.

    Returns:
        Filter names to drop on the bounded retry, in ``_SCOPE_FILTERS`` order.
    """
    active = [name for name in _SCOPE_FILTERS if filters.get(name) is not None]
    if not active or not missing_kinds:
        return []
    columns = ", ".join(f"count({name}) AS {name}" for name in active)
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {columns}
                FROM retrieval.documents
                WHERE is_current
                  AND evidence_kind = ANY(%s::text[])
                """,
                (missing_kinds,),
            )
            populated = cursor.fetchone()
    return [name for name in active if not populated[name]]


def _agent_search(
    request: AgentAnswerRequest,
    subquestion: dict[str, Any],
    filters: dict[str, Any],
    controls: dict[str, Any],
) -> dict[str, Any]:
    search_controls = {
        key: value for key, value in controls.items() if key != "mode"
    }
    return search_evidence_impl(
        subquestion["text"],
        kinds=request.kinds or subquestion["required_kinds"],
        role=request.role,
        limit=request.limit,
        **filters,
        **search_controls,
    )


def answer_question(request: AgentAnswerRequest) -> dict[str, Any]:
    started = perf_counter()
    plan = decompose_question_impl(request.question)
    filters = _agent_filters(request, plan["inferred_filters"])
    controls = _agent_controls(request)
    agent_run_id = _start_agent_run(request, plan, filters, controls)
    final_searches: list[dict[str, Any]] = []
    primary_run_id: str | None = None

    try:
        budget_exhausted = False
        for subquestion in plan["subquestions"]:
            if not _spend_agent_budget(agent_run_id, tool_calls=1, role=request.role):
                budget_exhausted = True
                break
            search = _agent_search(
                request,
                subquestion,
                filters,
                controls,
            )
            primary_run_id = primary_run_id or search["run_id"]
            coverage = _evaluate_coverage(
                search["run_id"],
                subquestion["required_kinds"],
                top_n=request.limit,
                role=request.role,
            )
            _persist_agent_retrieval(
                agent_run_id,
                subquestion,
                run_id=search["run_id"],
                attempt=1,
                coverage=coverage,
                role=request.role,
            )
            final_search = search

            if not coverage["covered"]:
                if not _spend_agent_budget(
                    agent_run_id,
                    tool_calls=1,
                    escalations=1,
                    role=request.role,
                ):
                    budget_exhausted = True
                    break
                escalated_controls = {
                    **controls,
                    "candidate_pool": min(
                        1000,
                        max(48, controls["candidate_pool"] * 2),
                    ),
                }
                escalated_controls["ef_search"] = min(
                    1000,
                    max(
                        200,
                        controls["ef_search"],
                        escalated_controls["candidate_pool"],
                    ),
                )
                unscoped = _unscoped_filters(
                    coverage["missing_kinds"],
                    filters,
                    request.role,
                )
                escalated_filters = {**filters, **dict.fromkeys(unscoped)}
                changed = {
                    "before": {
                        "controls": {
                            "candidate_pool": controls["candidate_pool"],
                            "ef_search": controls["ef_search"],
                        },
                        "filters": {name: filters.get(name) for name in unscoped},
                    },
                    "after": {
                        "controls": {
                            "candidate_pool": escalated_controls["candidate_pool"],
                            "ef_search": escalated_controls["ef_search"],
                        },
                        "filters": dict.fromkeys(unscoped),
                    },
                }
                rationale = (
                    "No indexed "
                    + " or ".join(coverage["missing_kinds"])
                    + " carries "
                    + " or ".join(sorted(unscoped))
                    + ", so that filter excludes the required evidence before "
                    "fusion. The bounded retry widens the candidate search and "
                    "drops the filter that cannot match."
                    if unscoped
                    else (
                        "The first retrieval did not cover every required evidence "
                        "kind, so the bounded retry widens the candidate pool and "
                        "HNSW search frontier without changing ACL policy."
                    )
                )
                escalated = _agent_search(
                    request,
                    subquestion,
                    escalated_filters,
                    escalated_controls,
                )
                escalated_coverage = _evaluate_coverage(
                    escalated["run_id"],
                    subquestion["required_kinds"],
                    top_n=request.limit,
                    role=request.role,
                )
                _persist_agent_retrieval(
                    agent_run_id,
                    subquestion,
                    run_id=escalated["run_id"],
                    attempt=2,
                    coverage=escalated_coverage,
                    role=request.role,
                )
                _persist_escalation(
                    agent_run_id,
                    subquestion,
                    attempt=2,
                    initial_coverage=coverage,
                    changed=changed,
                    rationale=rationale,
                    outcome=(
                        "covered"
                        if escalated_coverage["covered"]
                        else "still_uncovered"
                    ),
                    role=request.role,
                )
                final_search = escalated
            final_searches.append(final_search)

        if not final_searches or primary_run_id is None:
            status = "budget_exhausted" if budget_exhausted else "no_evidence"
            _finish_agent_run(agent_run_id, status, role=request.role)
            response = get_agent_run_impl(agent_run_id)
            response["agent"] = agent_metadata()
            response["plan"] = plan
            response["results"] = []
            response["comparison"] = {
                "evidence": [],
                "relationships": [],
                "observations": [],
            }
            response["total_latency_ms"] = max(
                0, round((perf_counter() - started) * 1000)
            )
            return response

        retrieved = []
        result_depth = max(
            (len(search["results"]) for search in final_searches),
            default=0,
        )
        for result_rank in range(result_depth):
            for search in final_searches:
                if result_rank < len(search["results"]):
                    retrieved.append(search["results"][result_rank])
        planned_keys = [
            key.upper()
            for subquestion in plan["subquestions"]
            for key in re.findall(
                r"\b(?:INC|CHG|CASE|RB|LOCK)-[A-Z0-9-]+\b",
                subquestion["text"],
                flags=re.IGNORECASE,
            )
        ]
        named_keys = list(
            dict.fromkeys([*plan["identified_keys"], *planned_keys])
        )
        seed_keys = list(
            dict.fromkeys(
                [
                    *named_keys,
                    *[
                        row["external_key"]
                        for row in retrieved[: max(2, request.limit)]
                    ],
                ]
            )
        )
        traversal = {"seeds": [], "reached": [], "relationship_count": 0}
        if _spend_agent_budget(agent_run_id, tool_calls=1, role=request.role):
            traversal_started = perf_counter()
            traversal = follow_evidence_links_impl(
                seed_keys,
                role=request.role,
                max_depth=2,
            )
            _append_agent_stage(
                primary_run_id,
                "follow evidence relationships",
                max(0, round((perf_counter() - traversal_started) * 1000)),
                {
                    "seed_keys": seed_keys,
                    "reached": len(traversal["reached"]),
                },
                role=request.role,
            )

        evidence = _merge_evidence(
            retrieved,
            traversal["reached"],
            named_keys=named_keys,
            limit=request.limit,
        )
        comparison = {
            "evidence": [],
            "relationships": [],
            "observations": [],
        }
        if evidence and _spend_agent_budget(agent_run_id, tool_calls=1, role=request.role):
            comparison_started = perf_counter()
            comparison = compare_sources_impl(
                [row["external_key"] for row in evidence],
                role=request.role,
            )
            evidence = _attach_relationships(
                evidence,
                comparison["relationships"],
            )
            _append_agent_stage(
                primary_run_id,
                "compare sources",
                max(0, round((perf_counter() - comparison_started) * 1000)),
                {
                    "evidence_count": len(comparison["evidence"]),
                    "relationship_count": len(comparison["relationships"]),
                },
                role=request.role,
            )

        synthesis_started = perf_counter()
        synthesis = synthesize_cited_answer_impl(
            request.question,
            evidence,
            run_id=primary_run_id,
            agent_run_id=agent_run_id,
            role=request.role,
        )
        _append_agent_stage(
            primary_run_id,
            "synthesize cited answer",
            max(0, round((perf_counter() - synthesis_started) * 1000)),
            {
                "mode": synthesis["synthesis"]["mode"],
                "citation_count": len(synthesis["citations"]),
            },
            role=request.role,
        )
        coverage = get_agent_coverage_impl(agent_run_id)
        uncovered = coverage["covered_count"] < coverage["subquestion_count"]
        status = (
            "no_evidence"
            if not retrieved
            else "budget_exhausted"
            if budget_exhausted
            else "partial"
            if uncovered
            else "complete"
        )
        _finish_agent_run(agent_run_id, status, role=request.role)
        response = get_agent_run_impl(agent_run_id)
        response.update(
            {
                "agent": agent_metadata(),
                "plan": plan,
                "results": evidence,
                "comparison": comparison,
                "total_latency_ms": max(
                    0, round((perf_counter() - started) * 1000)
                ),
            }
        )
        return response
    except Exception as error:
        _finish_agent_run(agent_run_id, "failed", error=str(error), role=request.role)
        raise


def answer_with_citations_impl(
    question: str,
    *,
    kinds: list[str] | None = None,
    cluster_id: str | None = None,
    incident_id: str | None = None,
    account_name: str | None = None,
    severities: list[str] | None = None,
    environment: str | None = None,
    service_name: str | None = None,
    engine_version: str | None = None,
    aws_region: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    role: str = "analyst",
    limit: int = 8,
    candidate_pool: int = 24,
    rrf_k: int = 60,
    w_text: float = 2.0,
    w_vector: float = 1.0,
    w_trgm: float = 1.0,
    fuzzy_threshold: float = 0.3,
    ef_search: int = 40,
    iterative_scan: str = "strict_order",
    rerank: bool = False,
    max_tool_calls: int = 12,
    max_escalations: int = 2,
) -> dict[str, Any]:
    """Run the whole deterministic agent loop and return a cited answer.

    Keyword-only adapter over :func:`answer_question` so every registry tool shares
    one ``impl(**kwargs)`` calling convention. The managed transports (stdio MCP,
    AgentCore Gateway) dispatch to this; the HTTP path uses ``answer_question``
    with a validated :class:`~backend.app.models.AgentAnswerRequest` directly.

    Args:
        question: The incident question, verbatim.
        role: The caller's persona; bound server-side, never set by the model.

    Returns:
        The agent run receipt: cited answer, citations, plan, and results.
    """
    return answer_question(
        AgentAnswerRequest(
            question=question,
            kinds=kinds,
            cluster_id=cluster_id,
            incident_id=incident_id,
            account_name=account_name,
            severities=severities,
            environment=environment,
            service_name=service_name,
            engine_version=engine_version,
            aws_region=aws_region,
            start_date=start_date,
            end_date=end_date,
            role=role,
            limit=limit,
            candidate_pool=candidate_pool,
            rrf_k=rrf_k,
            w_text=w_text,
            w_vector=w_vector,
            w_trgm=w_trgm,
            fuzzy_threshold=fuzzy_threshold,
            ef_search=ef_search,
            iterative_scan=iterative_scan,
            rerank=rerank,
            max_tool_calls=max_tool_calls,
            max_escalations=max_escalations,
        )
    )


def stream_answer(request: AgentAnswerRequest) -> Iterator[dict[str, Any]]:
    response = answer_question(request)
    yield {
        "type": "meta",
        "data": {
            key: response[key]
            for key in (
                "question",
                "agent_run_id",
                "run_id",
                "agent",
                "plan",
                "citations",
            )
            if key in response
        },
    }
    answer = response["answer"]
    for offset in range(0, len(answer), 32):
        yield {"type": "token", "data": {"text": answer[offset : offset + 32]}}
    yield {"type": "done", "data": response}
