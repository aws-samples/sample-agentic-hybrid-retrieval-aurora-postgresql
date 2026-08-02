from __future__ import annotations

import re
from string import Formatter
from textwrap import dedent
from typing import Any

from .config import get_settings
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector
from .models import QueryPlanRequest, SearchRequest
from .search import single_arm_sql
from .verify_sql import (
    EVIDENCE_EDGE_BATCH_SQL,
    OBSERVABILITY_REF_SQL,
    TIMELINE_EVENT_BATCH_SQL,
    edge_verify_sql,
    event_verify_sql,
)


FUSION_FUNCTIONS = [
    ("retrieval", "hybrid_search"),
    ("retrieval", "to_or_tsquery"),
    ("retrieval", "exact_identifier_match"),
    ("retrieval", "acl_visible"),
]


def _readiness_payload(
    health: dict[str, Any],
    embedding_spaces: list[dict[str, Any]],
) -> dict[str, Any]:
    if health["source_documents"] == 0:
        if health["drift_issues"] != 0:
            raise RuntimeError(
                "empty casework has search-index drift; apply the current schema"
            )
        return {
            "status": "awaiting_incident",
            "security_mode": "core",
            **health,
            "embedding_spaces": [],
        }
    if health["drift_issues"] != 0:
        raise RuntimeError(
            f"search index has {health['drift_issues']} operational drift issue(s)"
        )
    if health["current_documents"] != health["source_documents"]:
        raise RuntimeError(
            "current document count does not match the source document count"
        )
    if (
        health["current_chunks"] == 0
        or health["ready_embeddings"] != health["current_chunks"]
    ):
        raise RuntimeError("search index embeddings are not ready")
    if len(embedding_spaces) != 1:
        raise RuntimeError(
            f"expected one ready embedding space, found {len(embedding_spaces)}"
        )
    return {
        "status": "ready",
        "security_mode": "core",
        **health,
        "embedding_spaces": embedding_spaces,
    }


def _cluster_identity(cursor: Any) -> dict[str, Any]:
    """Fetch live engine identity for the SPEC 6.1 banner.

    The engine, pgvector, and cluster identities are read from the participant's
    live database state. Before a capture exists, cluster_id is intentionally
    null rather than a deployment default that might name another environment.
    """
    cursor.execute("SELECT version() AS engine_version")
    engine_version = cursor.fetchone()["engine_version"]
    cursor.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    )
    vector_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT cluster_id
        FROM casework.incident_capture_runs
        WHERE capture_origin = 'participant_induced'
        ORDER BY capture_started_at DESC
        LIMIT 1
        """
    )
    cluster_row = cursor.fetchone()
    return {
        "cluster_id": cluster_row["cluster_id"] if cluster_row else None,
        "engine_version": engine_version,
        "pgvector_version": vector_row["extversion"] if vector_row else None,
    }


def search_index_health() -> dict[str, Any]:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM retrieval.v_search_index_health")
            health = cursor.fetchone()
            cursor.execute("SELECT * FROM retrieval.v_embedding_spaces")
            embedding_spaces = cursor.fetchall()
            identity = _cluster_identity(cursor)
            live_run = _latest_live_run(cursor)
    return {
        **_readiness_payload(health, embedding_spaces),
        **identity,
        "run": live_run,
    }


def _latest_live_run(cursor: Any) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT
          capture.capture_id,
          capture.capture_key,
          capture.cluster_id,
          capture.capture_started_at,
          capture.capture_ended_at,
          incident.external_key AS incident_key,
          unsafe_change.external_key AS unsafe_change_key,
          repair_change.external_key AS repair_change_key,
          lock_item.external_key AS lock_key,
          (
            SELECT count(*)
            FROM casework.evidence_items item
            WHERE item.source_system = 'pg_incident_capture'
              AND NOT item.is_deleted
          ) AS source_documents,
          (
            SELECT count(*)
            FROM casework.telemetry_evidence telemetry
            WHERE telemetry.capture_id = capture.capture_id
          ) AS telemetry_documents,
          (
            SELECT count(*)
            FROM casework.pg_stat_activity_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) + (
            SELECT count(*)
            FROM casework.pg_lock_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) + (
            SELECT count(*)
            FROM casework.pg_blocking_pids_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) + (
            SELECT count(*)
            FROM casework.pg_stat_statements_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) + (
            SELECT count(*)
            FROM casework.cloudwatch_metric_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) + (
            SELECT count(*)
            FROM casework.database_insights_samples sample
            WHERE sample.capture_id = capture.capture_id
          ) AS raw_telemetry_rows
        FROM casework.incident_capture_runs capture
        JOIN casework.evidence_items incident
          ON incident.evidence_id = capture.incident_evidence_id
        JOIN casework.incident_changes unsafe_edge
          ON unsafe_edge.incident_evidence_id = incident.evidence_id
         AND unsafe_edge.relationship = 'confirmed'
        JOIN casework.evidence_items unsafe_change
          ON unsafe_change.evidence_id = unsafe_edge.change_evidence_id
        JOIN casework.incident_changes repair_edge
          ON repair_edge.incident_evidence_id = incident.evidence_id
         AND repair_edge.relationship = 'remediated'
        JOIN casework.evidence_items repair_change
          ON repair_change.evidence_id = repair_edge.change_evidence_id
        JOIN casework.lock_evidence lock_row
          ON lock_row.incident_evidence_id = incident.evidence_id
        JOIN casework.evidence_items lock_item
          ON lock_item.evidence_id = lock_row.evidence_id
        WHERE capture.capture_origin = 'participant_induced'
        ORDER BY capture.capture_started_at DESC
        LIMIT 1
        """
    )
    run = cursor.fetchone()
    if not run:
        return None
    return dict(run)


def latest_live_run() -> dict[str, Any] | None:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            return _latest_live_run(cursor)


def fusion_sql() -> dict[str, Any]:
    definitions: list[dict[str, str]] = []
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            for schema, name in FUSION_FUNCTIONS:
                cursor.execute(
                    """
                    SELECT pg_get_functiondef(proc.oid) AS definition
                    FROM pg_proc proc
                    JOIN pg_namespace namespace ON namespace.oid = proc.pronamespace
                    WHERE namespace.nspname = %s
                      AND proc.proname = %s
                    ORDER BY proc.pronargs DESC
                    LIMIT 1
                    """,
                    (schema, name),
                )
                row = cursor.fetchone()
                if row:
                    definitions.append(
                        {
                            "name": f"{schema}.{name}",
                            "definition": row["definition"],
                        }
                    )
    return {
        "engine": "Amazon Aurora PostgreSQL compatible",
        "primary": "retrieval.hybrid_search",
        "functions": definitions,
    }


def search_index_diagnostics() -> dict[str, Any]:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM retrieval.v_search_index_health")
            health = cursor.fetchone()
            cursor.execute("SELECT * FROM retrieval.v_embedding_spaces")
            embedding_spaces = cursor.fetchall()
            cursor.execute("SELECT * FROM retrieval.v_corpus_distribution")
            distribution = cursor.fetchall()
            drift = []
            if health["drift_issues"]:
                cursor.execute(
                    """
                    SELECT *
                    FROM retrieval.v_search_index_drift
                    ORDER BY issue, external_key
                    LIMIT 100
                    """
                )
                drift = cursor.fetchall()
            cursor.execute(
                """
                SELECT *
                FROM retrieval.search_index_builds
                ORDER BY started_at DESC
                LIMIT 10
                """
            )
            builds = cursor.fetchall()
            live_run = _latest_live_run(cursor)
    return {
        "health": health,
        "embedding_spaces": embedding_spaces,
        "distribution": distribution,
        "drift": drift,
        "recent_builds": builds,
        "run": live_run,
    }


def latest_cited_run(role: str = "app_engineer") -> dict[str, Any] | None:
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  answer.run_id,
                  answer.created_at
                FROM proof.agent_answers answer
                JOIN proof.retrieval_runs run USING (run_id)
                WHERE answer.validation_status = 'valid'
                  AND run.status = 'complete'
                  AND run.role = %s
                  AND EXISTS (
                    SELECT 1
                    FROM proof.answer_citations citation
                    WHERE citation.run_id = answer.run_id
                  )
                ORDER BY answer.created_at DESC, answer.run_id DESC
                LIMIT 1
                """,
                (role,),
            )
            return cursor.fetchone()


def index_usage() -> dict[str, Any]:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM retrieval.v_index_usage")
            usage = cursor.fetchall()
            cursor.execute("SELECT * FROM retrieval.v_index_definitions")
            definitions = cursor.fetchall()
    return {"usage": usage, "definitions": definitions}


def slow_queries() -> dict[str, Any]:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  queryid,
                  calls,
                  total_exec_time,
                  mean_exec_time,
                  rows,
                  left(query, 1200) AS query
                FROM pg_stat_statements
                WHERE query ILIKE '%%retrieval.%%'
                ORDER BY mean_exec_time DESC
                LIMIT 25
                """
            )
            rows = cursor.fetchall()
    return {"statements": rows}


def _plan_value(row: dict[str, Any]) -> Any:
    return row.get("QUERY PLAN") or next(iter(row.values()))


def _collect_scans(node: dict[str, Any], scans: list[dict[str, Any]]) -> None:
    if node.get("Node Type") in {
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
        "Bitmap Index Scan",
    }:
        scans.append(
            {
                "node_type": node.get("Node Type"),
                "relation": node.get("Relation Name"),
                "index": node.get("Index Name"),
                "actual_rows": node.get("Actual Rows"),
                "loops": node.get("Actual Loops"),
                "actual_startup_time_ms": node.get("Actual Startup Time"),
                "actual_total_time_ms": node.get("Actual Total Time"),
                "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                "shared_read_blocks": node.get("Shared Read Blocks", 0),
                "rows_removed_by_filter": node.get("Rows Removed by Filter", 0),
                "filter": node.get("Filter"),
                "index_cond": node.get("Index Cond"),
                "recheck_cond": node.get("Recheck Cond"),
            }
        )
    for child in node.get("Plans", []):
        _collect_scans(child, scans)


def _runtime_sql(arm: str, statement: str) -> str:
    parameterized = re.sub(
        r"%\(([^)]+)\)s",
        r":\1",
        dedent(statement).strip(),
    )
    setup: list[str] = []
    if arm == "semantic":
        setup.append(
            """SELECT retrieval.configure_ann_runtime(
  :ef_search::integer,
  :iterative_scan::text,
  :fuzzy_threshold::real
);"""
        )
    elif arm == "fuzzy":
        setup.append(
            """SELECT set_config(
  'pg_trgm.similarity_threshold',
  :fuzzy_threshold::text,
  true
);"""
        )

    explain = (
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n"
        f"{parameterized};"
    )
    return "\n\n".join([*setup, explain])


def _planner_summary(
    arm: str,
    scans: list[dict[str, Any]],
    fuzzy_probe_tokens: list[str],
) -> tuple[str, bool | None]:
    indexes = [scan["index"] for scan in scans if scan.get("index")]
    index_list = ", ".join(dict.fromkeys(indexes)) or "no named index"

    if arm == "semantic":
        hnsw_indexes = [name for name in indexes if "hnsw" in name.lower()]
        if hnsw_indexes:
            return (
                "The planner selected the HNSW path "
                f"({', '.join(hnsw_indexes)}). Filters and ACL checks remain "
                "inside the semantic arm before its positions enter fusion.",
                True,
            )
        return (
            "No HNSW index was selected for this capture. Under the current "
            f"filters and corpus statistics, PostgreSQL used {index_list} and "
            "sorted the bounded candidate set by vector distance. That is an "
            "observed planner choice, not a guarantee for another corpus or "
            "selectivity.",
            False,
        )

    if arm == "fuzzy" and not fuzzy_probe_tokens:
        return (
            "The fuzzy arm abstained before index traversal because the query "
            "contains no unresolved identifier-shaped token. It contributes "
            "zero to fusion by design.",
            None,
        )

    if arm == "fuzzy":
        return (
            f"The trigram arm probed {', '.join(fuzzy_probe_tokens)} through "
            f"{index_list}. The threshold and scope filters were applied before "
            "the arm assigned positions.",
            None,
        )

    return (
        f"The lexical arm used {index_list}. Exact identifier and full-text "
        "matches are deduplicated into one text position before fusion.",
        None,
    )


def query_plan(request: QueryPlanRequest) -> dict[str, Any]:
    settings = get_settings()
    embedding = None
    if request.arm == "semantic":
        embedding = to_pgvector(
            embed_text(
                request.query,
                provider=settings.embed_provider,
                dim=settings.embed_dim,
                input_type="search_query",
            )
        )
    search_request = SearchRequest(
        query=request.query,
        mode=request.arm,
        kinds=request.kinds,
        source_systems=request.source_systems,
        cluster_id=request.cluster_id,
        limit=request.limit,
        role=request.role,
    )
    statement, params = single_arm_sql(search_request, embedding=embedding)

    with get_dict_conn(request.role) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                if request.arm == "semantic":
                    cursor.execute(
                        """
                        SELECT retrieval.configure_ann_runtime(
                          %s::integer,
                          %s::text,
                          %s::real
                        )
                        """,
                        (
                            search_request.ef_search,
                            search_request.iterative_scan,
                            search_request.fuzzy_threshold,
                        ),
                    )
                elif request.arm == "fuzzy":
                    cursor.execute(
                        "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                        (str(search_request.fuzzy_threshold),),
                    )
                cursor.execute(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}",
                    params,
                )
                payload = _plan_value(cursor.fetchone())
                cursor.execute("SELECT clock_timestamp() AS captured_at")
                captured_at = cursor.fetchone()["captured_at"]
    plan = payload[0] if isinstance(payload, list) else payload
    scans: list[dict[str, Any]] = []
    _collect_scans(plan["Plan"], scans)
    fuzzy_probe_tokens = (
        params["fuzzy_probe_tokens"] if request.arm == "fuzzy" else []
    )
    planner_summary, uses_hnsw = _planner_summary(
        request.arm,
        scans,
        fuzzy_probe_tokens,
    )
    result = {
        "arm": request.arm,
        "query": request.query,
        "source_systems": request.source_systems,
        "cluster_id": request.cluster_id,
        "captured_at": captured_at,
        "plan": plan,
        "scans": scans,
        "runtime_sql": _runtime_sql(request.arm, statement),
        "planner_summary": planner_summary,
        "uses_hnsw": uses_hnsw,
        "note": (
            "This explains the canonical retrieval SQL function. Planner choices depend on corpus "
            "size, selectivity, statistics, runtime settings, and cache state."
        ),
        "_verify_sql": {
            "reproducible": False,
            "reason": (
                "live EXPLAIN (ANALYZE) capture, not run-bound: the plan reflects "
                "current statistics and cache state and embeds a freshly computed "
                "query embedding, so it cannot be replayed byte-for-byte from a run_id."
            ),
        },
    }
    if request.arm == "fuzzy":
        result["fuzzy_probe_tokens"] = fuzzy_probe_tokens
        if not fuzzy_probe_tokens:
            result["abstained"] = True
            result["abstain_reason"] = (
                "The trigram arm probes identifier tokens that no indexed document "
                "answers exactly. This query named none, so the arm returns no rows "
                "and contributes nothing to fusion."
            )
    return result


def _run_role(run_id: str, viewer_role: str) -> str:
    """Require a retrieval run to match the viewer's request context.

    Replay uses the run's persisted context so a receipt shows the original
    request rather than silently relabeling it.

    Args:
        run_id: The run whose stored identity is needed.

    Returns:
        One of db.PERSONAS.

    Raises:
        ValueError: No such run.
    """
    with get_dict_conn(viewer_role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT role FROM proof.retrieval_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cursor.fetchone()
    if not row or row["role"] != viewer_role:
        raise ValueError(
            f"retrieval run {run_id} was not found for persona {viewer_role}"
        )
    return row["role"]


def run_graph(run_id: str, role: str = "app_engineer") -> dict[str, Any]:
    stored_role = _run_role(run_id, role)
    with get_dict_conn(stored_role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT evidence_id
                FROM proof.retrieval_candidates
                WHERE run_id = %s
                ORDER BY evidence_id
                """,
                (run_id,),
            )
            seeds = [row["evidence_id"] for row in cursor.fetchall()]
            if not seeds:
                return {"run_id": run_id, "nodes": [], "edges": []}
            cursor.execute(
                """
                SELECT *
                FROM retrieval.traverse_evidence(%s::uuid[], 2)
                """,
                (seeds,),
            )
            reached = cursor.fetchall()
            reached_ids = [row["evidence_id"] for row in reached]
            cursor.execute(EVIDENCE_EDGE_BATCH_SQL, {"ids": reached_ids})
            edges = cursor.fetchall()
    for edge in edges:
        edge["_verify_sql"] = edge_verify_sql(edge["edge_key"], stored_role)
    return {
        "run_id": run_id,
        "nodes": reached,
        "edges": edges,
        "node_count": len(reached),
        "edge_count": len(edges),
    }


def _render_deep_link(template: str, values: dict[str, str]) -> str | None:
    """Render a console URL template, or return None if it cannot be completed.

    A link is only offered when the operator configured a template and every
    placeholder the template names resolves to a non-empty value. A template that
    references ``{window_start}`` when the run has no window, or ``{db_resource_id}``
    when the deployment set none, yields None rather than a broken URL. This is
    what keeps the button honest: no template, or an unresolved placeholder, means
    no button (SPEC 6.3 / 5.4).
    """
    if not template:
        return None
    fields = {
        name for _, name, _, _ in Formatter().parse(template) if name
    }
    if any(not values.get(name) for name in fields):
        return None
    return template.format(**values)


def observability_ref(
    run_id: str,
    role: str = "app_engineer",
) -> dict[str, Any]:
    """Return the Database Insights hand-off for a run (SPEC 6.3).

    The observability window is read from ``proof.observability_refs``; the deep
    links are composed from it plus deployment config and appear only when a URL
    template is configured and fully resolvable. When no row exists (a run that
    predates this table, or a failed run) the whole ref is None.

    Args:
        run_id: The run whose observability window is being surfaced.

    Returns:
        A payload with the stored window, any composed deep links, and a
        ``_verify_sql`` descriptor for the window row; or ``{"run_id", "ref": None}``
        when the run has no observability row.
    """
    stored_role = _run_role(run_id, role)
    with get_dict_conn(stored_role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(OBSERVABILITY_REF_SQL, {"run_id": run_id})
            ref = cursor.fetchone()
    if not ref:
        return {"run_id": run_id, "ref": None, "links": []}

    settings = get_settings()
    values = {
        "region": settings.workbench_region,
        "db_resource_id": ref.get("db_resource_id") or "",
        "window_start": ref["window_start"].isoformat()
        if ref.get("window_start")
        else "",
        "window_end": ref["window_end"].isoformat()
        if ref.get("window_end")
        else "",
    }
    links = [
        {
            "kind": kind,
            "label": label,
            "url": url,
        }
        for kind, label, template in (
            (
                "database_insights",
                "Open in Database Insights",
                settings.workbench_dbi_url_template,
            ),
            (
                "lock_analysis",
                "Open lock analysis",
                settings.workbench_lock_url_template,
            ),
        )
        if (url := _render_deep_link(template, values))
    ]
    return {
        "run_id": run_id,
        "ref": ref,
        "links": links,
        "_verify_sql": {"statement": OBSERVABILITY_REF_SQL, "binds": {"run_id": run_id}},
    }


def run_timeline(run_id: str, role: str = "app_engineer") -> dict[str, Any]:
    graph = run_graph(run_id, role=role)
    ids = [row["evidence_id"] for row in graph["nodes"]]
    if not ids:
        return {"run_id": run_id, "events": [], "edge_count": 0}
    stored_role = _run_role(run_id, role)
    with get_dict_conn(stored_role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(TIMELINE_EVENT_BATCH_SQL, {"ids": ids})
            events = cursor.fetchall()
    for event in events:
        event["_verify_sql"] = event_verify_sql(event["evidence_id"], stored_role)
    return {
        "run_id": run_id,
        "events": events,
        "edge_count": graph["edge_count"],
    }
