from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from .config import get_settings
from .contracts import CONTRACT_VERSION
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector
from .models import SearchRequest
from .rerank import get_cohere_rerank_service

logger = logging.getLogger(__name__)
# Identifier-shaped tokens: a short alphabetic prefix, a hyphen, then a 3-6
# character suffix containing at least one digit.
#
# The suffix admits letters so that letter-for-digit typos, such as CHG-1B42 for
# CHG-1842, are still recognized as identifier-shaped. A digits-only suffix
# would discard them before the trigram arm ever saw them, which is the one case
# fuzzy matching exists to serve. Requiring a digit keeps ordinary hyphenated
# words such as read-only from being read as identifiers.
IDENTIFIER_PATTERN = re.compile(
    r"\b[A-Z]{2,6}-(?=[A-Z0-9]*[0-9])[A-Z0-9]{3,6}\b",
    re.IGNORECASE,
)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _elapsed_ms(start: float) -> int:
    return max(0, round((perf_counter() - start) * 1000))


def _uses_vectors(mode: str) -> bool:
    return mode in {"hybrid", "semantic"}


def _query_embedding_model() -> str:
    settings = get_settings()
    if settings.embed_provider == "hash":
        return "local-hash-embedding-v1"
    return settings.bedrock_embedding_model


def _rerank_enabled(request: SearchRequest) -> bool:
    if request.rerank is not None:
        return request.rerank
    return request.mode == "hybrid" and get_settings().cohere_rerank_enabled


def _candidate_limit(request: SearchRequest, rerank_enabled: bool) -> int:
    if not rerank_enabled:
        return request.limit
    return min(
        max(request.limit * 3, request.limit),
        get_settings().cohere_rerank_max_documents,
    )


def _filters(request: SearchRequest) -> dict[str, Any]:
    return {
        "kinds": request.kinds,
        "cluster_id": request.cluster_id,
        "incident_id": request.incident_id,
        "account_name": request.account_name,
        "severities": request.severities,
        "environment": request.environment,
        "service_name": request.service_name,
        "engine_version": request.engine_version,
        "aws_region": request.aws_region,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }


def _create_run(
    request: SearchRequest,
    *,
    embedding_model: str | None,
    rerank_enabled: bool,
    identifier_tokens: list[str],
    fuzzy_probe_tokens: list[str],
) -> str:
    settings = get_settings()
    with get_dict_conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.retrieval_runs(
                  query_text,
                  embedding_model,
                  retrieval_mode,
                  filters,
                  principal,
                  rrf_k,
                  text_weight,
                  vector_weight,
                  fuzzy_weight,
                  fuzzy_threshold,
                  identifier_tokens,
                  fuzzy_probe_tokens,
                  candidate_pool,
                  hnsw_ef_search,
                  hnsw_iterative_scan,
                  rerank_model,
                  status
                )
                VALUES (
                  %(query)s,
                  %(embedding_model)s,
                  %(mode)s,
                  %(filters)s::jsonb,
                  %(principal)s::jsonb,
                  %(rrf_k)s,
                  %(w_text)s,
                  %(w_vector)s,
                  %(w_trgm)s,
                  %(fuzzy_threshold)s,
                  %(identifier_tokens)s::text[],
                  %(fuzzy_probe_tokens)s::text[],
                  %(candidate_pool)s,
                  %(ef_search)s,
                  %(iterative_scan)s,
                  %(rerank_model)s,
                  'running'
                )
                RETURNING run_id
                """,
                {
                    "query": request.query,
                    "embedding_model": embedding_model,
                    "mode": request.mode,
                    "filters": _json(_filters(request)),
                    "principal": _json(request.principal),
                    "rrf_k": request.rrf_k,
                    "w_text": request.w_text,
                    "w_vector": request.w_vector,
                    "w_trgm": request.w_trgm,
                    "fuzzy_threshold": request.fuzzy_threshold,
                    "identifier_tokens": identifier_tokens,
                    "fuzzy_probe_tokens": fuzzy_probe_tokens,
                    "candidate_pool": request.candidate_pool,
                    "ef_search": request.ef_search if _uses_vectors(request.mode) else None,
                    "iterative_scan": (
                        request.iterative_scan if _uses_vectors(request.mode) else None
                    ),
                    "rerank_model": (
                        settings.cohere_rerank_model if rerank_enabled else None
                    ),
                },
            )
            return str(cursor.fetchone()["run_id"])


def _identifier_tokens(query: str) -> list[str]:
    return sorted({match.upper() for match in IDENTIFIER_PATTERN.findall(query)})


def _resolve_fuzzy_probe_tokens(
    request: SearchRequest,
    identifier_tokens: list[str],
) -> list[str]:
    """Return the identifier tokens that no indexed document answers exactly.

    Existence is deliberately evaluated without the caller's ACL. Fuzzing a
    token the caller may not read would let the trigram arm return its visible
    near neighbours, which tells the caller that a restricted identifier is
    indexed. The arms still apply the ACL to everything they return, so an
    unreadable exact match yields no rows rather than a near-miss substitute.
    """
    if not identifier_tokens:
        return []

    with get_dict_conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT probe.token
                FROM unnest(%(tokens)s::text[]) AS probe(token)
                WHERE NOT EXISTS (
                  SELECT 1
                  FROM retrieval.documents document
                  WHERE document.is_current
                    AND document.index_state = 'ready'
                    AND upper(document.external_key) = probe.token
                    AND (
                      %(kinds)s::text[] IS NULL
                      OR document.evidence_kind = ANY(%(kinds)s::text[])
                    )
                    AND (
                      %(cluster_id)s::text IS NULL
                      OR document.cluster_id = %(cluster_id)s::text
                    )
                    AND (
                      %(incident_id)s::text IS NULL
                      OR document.incident_id = %(incident_id)s::text
                    )
                    AND (
                      %(account_name)s::text IS NULL
                      OR document.account_name = %(account_name)s::text
                    )
                    AND (
                      %(severities)s::text[] IS NULL
                      OR document.severity = ANY(%(severities)s::text[])
                    )
                    AND (
                      %(environment)s::text IS NULL
                      OR document.environment = %(environment)s::text
                    )
                    AND (
                      %(service_name)s::text IS NULL
                      OR document.service_name = %(service_name)s::text
                    )
                    AND (
                      %(engine_version)s::text IS NULL
                      OR document.engine_version = %(engine_version)s::text
                    )
                    AND (
                      %(aws_region)s::text IS NULL
                      OR document.aws_region = %(aws_region)s::text
                    )
                    AND (
                      %(start_date)s::timestamptz IS NULL
                      OR document.occurred_at >= %(start_date)s::timestamptz
                    )
                    AND (
                      %(end_date)s::timestamptz IS NULL
                      OR document.occurred_at <= %(end_date)s::timestamptz
                    )
                )
                ORDER BY probe.token
                """,
                {**_filters(request), "tokens": identifier_tokens},
            )
            return [row["token"] for row in cursor.fetchall()]


def _mark_run_failed(run_id: str, error: Exception, latency_ms: int) -> None:
    try:
        with get_dict_conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proof.retrieval_runs
                    SET status = 'failed',
                        completed_at = now(),
                        latency_ms = %s,
                        error = %s
                    WHERE run_id = %s
                    """,
                    (latency_ms, str(error)[:4000], run_id),
                )
    except Exception as receipt_error:
        logger.error(
            "Could not persist failed retrieval receipt %s: %s",
            run_id,
            receipt_error,
        )


def _assert_embedding_space(cursor, model_id: str) -> None:
    cursor.execute(
        """
        SELECT embedding_model, dimensions
        FROM retrieval.v_embedding_spaces
        ORDER BY embedding_model
        """
    )
    spaces = cursor.fetchall()
    if len(spaces) != 1:
        raise RuntimeError(
            f"expected one ready embedding space, found {len(spaces)}"
        )
    space = spaces[0]
    expected_dim = get_settings().embed_dim
    if space["embedding_model"] != model_id or space["dimensions"] != expected_dim:
        raise RuntimeError(
            "query embedding space does not match indexed chunks: "
            f"query={model_id}/{expected_dim} indexed="
            f"{space['embedding_model']}/{space['dimensions']}"
        )


def _common_params(
    request: SearchRequest,
    *,
    result_limit: int,
    fuzzy_probe_tokens: list[str],
) -> dict[str, Any]:
    return {
        "query": request.query,
        "kinds": request.kinds,
        "cluster_id": request.cluster_id,
        "incident_id": request.incident_id,
        "account_name": request.account_name,
        "severities": request.severities,
        "environment": request.environment,
        "service_name": request.service_name,
        "engine_version": request.engine_version,
        "aws_region": request.aws_region,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "principal": _json(request.principal),
        "limit": result_limit,
        "candidate_pool": request.candidate_pool,
        "rrf_k": request.rrf_k,
        "w_text": request.w_text,
        "w_vector": request.w_vector,
        "w_trgm": request.w_trgm,
        "fuzzy_threshold": request.fuzzy_threshold,
        "fuzzy_probe_tokens": fuzzy_probe_tokens,
    }


_FILTER_ARGUMENTS = """
  p_kinds => %(kinds)s::text[],
  p_cluster_id => %(cluster_id)s::text,
  p_incident_id => %(incident_id)s::text,
  p_account_name => %(account_name)s::text,
  p_severities => %(severities)s::text[],
  p_environment => %(environment)s::text,
  p_service_name => %(service_name)s::text,
  p_engine_version => %(engine_version)s::text,
  p_aws_region => %(aws_region)s::text,
  p_start_date => %(start_date)s::timestamptz,
  p_end_date => %(end_date)s::timestamptz,
  p_principal => %(principal)s::jsonb,
  p_limit => %(limit)s::integer
"""


_ARM_STATEMENTS = {
    "semantic": f"""
        SELECT *
        FROM retrieval.vector_search(
          p_query_embedding => %(embedding)s::vector,
          {_FILTER_ARGUMENTS},
          p_candidate_pool => %(candidate_pool)s::integer
        )
    """,
    "lexical": f"""
        SELECT *
        FROM retrieval.full_text_search(
          p_query => %(query)s,
          {_FILTER_ARGUMENTS}
        )
    """,
    "fuzzy": f"""
        SELECT *
        FROM retrieval.fuzzy_search(
          p_probe_tokens => %(fuzzy_probe_tokens)s::text[],
          p_threshold => %(fuzzy_threshold)s::real,
          {_FILTER_ARGUMENTS}
        )
    """,
}


def single_arm_sql(
    request: SearchRequest,
    *,
    embedding: str | None,
) -> tuple[str, dict[str, Any]]:
    """Return the statement and parameters for one retrieval arm.

    The query-plan diagnostic explains what retrieval actually runs by calling
    this, so a change to an arm's SQL signature cannot leave the diagnostic
    explaining a function that no longer exists.

    Args:
        request: The retrieval request, whose mode selects the arm.
        embedding: Query embedding as a pgvector literal, for the semantic arm.

    Returns:
        The parameterized SELECT over that arm's SQL function, and its binds.
    """
    tokens = _identifier_tokens(request.query)
    params = _common_params(
        request,
        result_limit=request.limit,
        fuzzy_probe_tokens=_resolve_fuzzy_probe_tokens(request, tokens),
    )
    params["embedding"] = embedding
    return _ARM_STATEMENTS[request.mode], params


def _normalize_single_signal(
    rows: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    score_field = {
        "semantic": "vector_score",
        "lexical": "text_rank",
        "fuzzy": "trigram_score",
    }[mode]
    position_field = {
        "semantic": "vector_position",
        "lexical": "text_position",
        "fuzzy": "trigram_position",
    }[mode]
    normalized: list[dict[str, Any]] = []
    for rank, source in enumerate(rows, start=1):
        row = dict(source)
        raw_score = float(row.pop("score", 0.0) or 0.0)
        base_explanation = dict(row.get("explanation") or {})
        row.update(
            {
                "text_rank": None,
                "vector_score": None,
                "trigram_score": None,
                "text_position": None,
                "vector_position": None,
                "trigram_position": None,
                "exact_identifier_position": None,
                "match_tier": 2,
                "rrf_score": 0.0,
                "final_score": raw_score,
            }
        )
        row[score_field] = raw_score
        row[position_field] = rank
        row["explanation"] = {
            **base_explanation,
            "signals": {mode: raw_score},
            "positions": {mode: rank},
            "match_tier": 2,
            "match_tier_label": "single_signal",
            "note": (
                f"Single-signal {mode} retrieval; no fusion and no exact-identifier "
                "tier were applied."
            ),
        }
        normalized.append(row)
    return normalized


def _run_sql_search(
    request: SearchRequest,
    *,
    embedding: str | None,
    embedding_model: str | None,
    result_limit: int,
    fuzzy_probe_tokens: list[str],
) -> list[dict[str, Any]]:
    params = _common_params(
        request,
        result_limit=result_limit,
        fuzzy_probe_tokens=fuzzy_probe_tokens,
    )
    params["embedding"] = embedding
    with get_dict_conn() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                if _uses_vectors(request.mode):
                    if embedding is None or embedding_model is None:
                        raise RuntimeError(
                            f"{request.mode} retrieval requires a query embedding"
                        )
                    _assert_embedding_space(cursor, embedding_model)
                    cursor.execute(
                        """
                        SELECT retrieval.configure_ann_runtime(
                          %s::integer,
                          %s::text,
                          %s::real
                        )
                        """,
                        (
                            request.ef_search,
                            request.iterative_scan,
                            request.fuzzy_threshold,
                        ),
                    )
                elif request.mode == "fuzzy":
                    cursor.execute(
                        "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                        (str(request.fuzzy_threshold),),
                    )

                if request.mode == "hybrid":
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM retrieval.hybrid_search(
                          p_query => %(query)s,
                          p_query_embedding => %(embedding)s::vector,
                          p_fuzzy_probe_tokens => %(fuzzy_probe_tokens)s::text[],
                          {_FILTER_ARGUMENTS},
                          p_candidate_pool => %(candidate_pool)s::integer,
                          p_rrf_k => %(rrf_k)s::integer,
                          p_w_text => %(w_text)s::numeric,
                          p_w_vector => %(w_vector)s::numeric,
                          p_w_trgm => %(w_trgm)s::numeric,
                          p_fuzzy_threshold => %(fuzzy_threshold)s::real
                        )
                        """,
                        params,
                    )
                    return cursor.fetchall()

                cursor.execute(_ARM_STATEMENTS[request.mode], params)
                return _normalize_single_signal(cursor.fetchall(), request.mode)


def _candidate_document(row: dict[str, Any]) -> str:
    fields = [
        f"Kind: {row.get('evidence_kind')}",
        f"External key: {row.get('external_key')}",
        f"Title: {row.get('title')}",
        f"Cluster: {row.get('cluster_id')}" if row.get("cluster_id") else "",
        f"Incident: {row.get('incident_id')}" if row.get("incident_id") else "",
        f"Account: {row.get('account_name')}" if row.get("account_name") else "",
        f"Severity: {row.get('severity')}" if row.get("severity") else "",
        f"Service: {row.get('service_name')}" if row.get("service_name") else "",
        (
            f"Engine version: {row.get('engine_version')}"
            if row.get("engine_version")
            else ""
        ),
        f"Region: {row.get('aws_region')}" if row.get("aws_region") else "",
        f"Evidence: {row.get('snippet')}",
    ]
    return "\n".join(field for field in fields if field)[:4000]


def _apply_rerank(
    query: str,
    rows: list[dict[str, Any]],
    *,
    top_n: int,
    enabled: bool,
) -> tuple[list[dict[str, Any]], bool]:
    if not enabled or not rows:
        return rows, False
    results = get_cohere_rerank_service().rerank(
        query,
        [_candidate_document(row) for row in rows],
        top_n=top_n,
    )
    if not results:
        return rows, False

    selected: set[int] = set()
    ordered: list[dict[str, Any]] = []
    for result in results:
        index = result.get("index")
        if (
            not isinstance(index, int)
            or index < 0
            or index >= len(rows)
            or index in selected
        ):
            continue
        selected.add(index)
        row = dict(rows[index])
        row["rerank_score"] = float(result.get("relevance_score") or 0.0)
        explanation = dict(row.get("explanation") or {})
        explanation["rerank"] = {
            "model": get_settings().cohere_rerank_model,
            "score": row["rerank_score"],
            "note": "Post-fusion ordering signal; not a probability.",
        }
        row["explanation"] = explanation
        ordered.append(row)
    if not ordered:
        return rows, False
    ordered.extend(row for index, row in enumerate(rows) if index not in selected)
    # The exact-identifier tier survives reranking. Cohere scores relevance, not
    # identity: it has no way to know that the caller named an identifier, so
    # letting it interleave tiers would reintroduce exactly the demotion the tier
    # exists to prevent. sorted() is stable, so the model's order is preserved
    # inside each tier.
    ordered.sort(key=lambda row: row.get("match_tier") or 2)
    return ordered, True


def _evidence_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "evidence_id",
        "evidence_kind",
        "external_key",
        "title",
        "source_system",
        "source_uri",
        "source_revision",
        "cluster_id",
        "incident_id",
        "account_name",
        "severity",
        "environment",
        "service_name",
        "engine_version",
        "aws_region",
        "occurred_at",
        "snippet",
    )
    return {key: row.get(key) for key in keys}


def _match_tier_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe the returned rows as ordered ranking groups.

    Args:
        rows: Result rows in final ranking order.

    Returns:
        One entry per non-empty tier, in ranking order, each carrying the tier
        number, a stable label, its row count, and the rank range it occupies.
    """
    labels = {1: "Exact identifier", 2: "Fused candidates"}
    summary: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        tier = row.get("match_tier") or 2
        if summary and summary[-1]["tier"] == tier:
            summary[-1]["count"] += 1
            summary[-1]["last_rank"] = rank
            continue
        summary.append(
            {
                "tier": tier,
                "label": labels.get(tier, f"Tier {tier}"),
                "count": 1,
                "first_rank": rank,
                "last_rank": rank,
            }
        )
    return summary


def _persist_success(
    run_id: str,
    request: SearchRequest,
    rows: list[dict[str, Any]],
    *,
    embedding: str | None,
    rerank_applied: bool,
    stages: list[dict[str, Any]],
    total_start: float,
) -> None:
    persist_start = perf_counter()
    with get_dict_conn() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO proof.retrieval_candidates(
                      run_id,
                      evidence_id,
                      document_version_id,
                      chunk_version_id,
                      result_rank,
                      text_rank,
                      vector_score,
                      trigram_score,
                      text_position,
                      vector_position,
                      trigram_position,
                      exact_identifier_position,
                      match_tier,
                      rrf_score,
                      rerank_score,
                      final_score,
                      explanation,
                      evidence_snapshot
                    )
                    VALUES (
                      %(run_id)s,
                      %(evidence_id)s,
                      %(document_version_id)s,
                      %(chunk_version_id)s,
                      %(result_rank)s,
                      %(text_rank)s,
                      %(vector_score)s,
                      %(trigram_score)s,
                      %(text_position)s,
                      %(vector_position)s,
                      %(trigram_position)s,
                      %(exact_identifier_position)s,
                      %(match_tier)s,
                      %(rrf_score)s,
                      %(rerank_score)s,
                      %(final_score)s,
                      %(explanation)s::jsonb,
                      %(evidence_snapshot)s::jsonb
                    )
                    """,
                    [
                        {
                            "run_id": run_id,
                            "evidence_id": row["evidence_id"],
                            "document_version_id": row["document_version_id"],
                            "chunk_version_id": row["chunk_version_id"],
                            "result_rank": rank,
                            "text_rank": row.get("text_rank"),
                            "vector_score": row.get("vector_score"),
                            "trigram_score": row.get("trigram_score"),
                            "text_position": row.get("text_position"),
                            "vector_position": row.get("vector_position"),
                            "trigram_position": row.get("trigram_position"),
                            "exact_identifier_position": row.get(
                                "exact_identifier_position"
                            ),
                            "match_tier": row.get("match_tier") or 2,
                            "rrf_score": row.get("rrf_score") or 0,
                            "rerank_score": row.get("rerank_score"),
                            "final_score": row.get("final_score") or 0,
                            "explanation": _json(row.get("explanation") or {}),
                            "evidence_snapshot": _json(_evidence_snapshot(row)),
                        }
                        for rank, row in enumerate(rows, start=1)
                    ],
                )
                stages.append(
                    {
                        "stage": "persist receipt",
                        "ms": _elapsed_ms(persist_start),
                        "details": {"candidate_count": len(rows)},
                    }
                )
                cursor.executemany(
                    """
                    INSERT INTO proof.run_stages(
                      run_id, stage_ordinal, stage_name, duration_ms, details
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    [
                        (
                            run_id,
                            ordinal,
                            stage["stage"],
                            stage["ms"],
                            _json(stage.get("details") or {}),
                        )
                        for ordinal, stage in enumerate(stages, start=1)
                    ],
                )
                cursor.execute(
                    """
                    UPDATE proof.retrieval_runs
                    SET query_embedding = %(embedding)s::vector,
                        rerank_applied = %(rerank_applied)s,
                        status = 'complete',
                        completed_at = now(),
                        latency_ms = %(latency_ms)s,
                        error = NULL
                    WHERE run_id = %(run_id)s
                    """,
                    {
                        "embedding": embedding,
                        "rerank_applied": rerank_applied,
                        "latency_ms": _elapsed_ms(total_start),
                        "run_id": run_id,
                    },
                )


def run_hybrid_search(request: SearchRequest) -> dict[str, Any]:
    total_start = perf_counter()
    rerank_enabled = _rerank_enabled(request)
    embedding_model = _query_embedding_model() if _uses_vectors(request.mode) else None
    identifier_tokens = _identifier_tokens(request.query)
    fuzzy_probe_tokens = _resolve_fuzzy_probe_tokens(
        request,
        identifier_tokens,
    )
    run_id = _create_run(
        request,
        embedding_model=embedding_model,
        rerank_enabled=rerank_enabled,
        identifier_tokens=identifier_tokens,
        fuzzy_probe_tokens=fuzzy_probe_tokens,
    )
    stages: list[dict[str, Any]] = []
    try:
        if (
            _uses_vectors(request.mode)
            and request.ef_search < request.candidate_pool
        ):
            raise ValueError(
                "ef_search must be greater than or equal to candidate_pool "
                f"({request.ef_search} < {request.candidate_pool})"
            )

        embedding: str | None = None
        if _uses_vectors(request.mode):
            started = perf_counter()
            settings = get_settings()
            embedding = to_pgvector(
                embed_text(
                    request.query,
                    provider=settings.embed_provider,
                    dim=settings.embed_dim,
                    input_type="search_query",
                )
            )
            stages.append(
                {
                    "stage": "embed query",
                    "ms": _elapsed_ms(started),
                    "details": {"model": embedding_model},
                }
            )

        candidate_limit = _candidate_limit(request, rerank_enabled)
        started = perf_counter()
        rows = _run_sql_search(
            request,
            embedding=embedding,
            embedding_model=embedding_model,
            result_limit=candidate_limit,
            fuzzy_probe_tokens=fuzzy_probe_tokens,
        )
        stages.append(
            {
                "stage": f"{request.mode} retrieval",
                "ms": _elapsed_ms(started),
                "details": {
                    "candidate_limit": candidate_limit,
                    "returned": len(rows),
                },
            }
        )

        started = perf_counter()
        ordered_rows, rerank_applied = _apply_rerank(
            request.query,
            rows,
            top_n=request.limit,
            enabled=rerank_enabled,
        )
        if rerank_enabled:
            stages.append(
                {
                    "stage": "model rerank",
                    "ms": _elapsed_ms(started),
                    "details": {
                        "model": get_settings().cohere_rerank_model,
                        "applied": rerank_applied,
                    },
                }
            )

        _persist_success(
            run_id,
            request,
            ordered_rows,
            embedding=embedding,
            rerank_applied=rerank_applied,
            stages=stages,
            total_start=total_start,
        )
    except Exception as error:
        _mark_run_failed(run_id, error, _elapsed_ms(total_start))
        raise

    public_rows = ordered_rows[: request.limit]
    return {
        "contract_version": CONTRACT_VERSION,
        "run_id": run_id,
        "query": request.query,
        "mode": request.mode,
        "retrieval_mode": request.mode,
        "rerank_applied": rerank_applied,
        "knobs": {
            "rrf_k": request.rrf_k,
            "weights": {
                "text": request.w_text,
                "vector": request.w_vector,
                "fuzzy": request.w_trgm,
            },
            "ef_search": request.ef_search,
            "iterative_scan": request.iterative_scan,
            "fuzzy_threshold": request.fuzzy_threshold,
            "identifier_tokens": identifier_tokens,
            "fuzzy_probe_tokens": fuzzy_probe_tokens,
        },
        "candidate_count": len(ordered_rows),
        "match_tiers": _match_tier_summary(public_rows),
        "stage_timings": stages,
        "total_latency_ms": _elapsed_ms(total_start),
        "results": public_rows,
    }
