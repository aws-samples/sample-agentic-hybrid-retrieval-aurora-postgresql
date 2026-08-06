#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bedrock import get_bedrock_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import close_pool, get_owner_conn  # noqa: E402
from app.embeddings import embed_text  # noqa: E402
from app.rerank import CohereRerankService  # noqa: E402

REQUIRED_EXTENSIONS = ("vector", "pg_trgm", "pg_stat_statements")
EXPECTED_INCIDENT_PHASES = (
    "backfill",
    "pool_exhaustion",
    "recovery",
    "plan_regression",
)
EXPECTED_SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")
# Gate 5 measured 50-80 documents as the honest result of one incident run.
# This is an advisory range, never an acceptance condition: behavior and
# category coverage are the release contract.
EXPECTED_LIVE_DOCUMENT_RANGE = (50, 80)
REQUIRED_TABLES = (
    "casework.database_clusters",
    "casework.evidence_items",
    "casework.incidents",
    "casework.changes",
    "casework.incident_capture_runs",
    "casework.lock_evidence",
    "casework.pg_stat_activity_samples",
    "casework.pg_lock_samples",
    "casework.pg_blocking_pids_samples",
    "casework.pg_stat_statements_samples",
    "casework.cloudwatch_metric_samples",
    "casework.telemetry_evidence",
    "casework.incident_changes",
    "retrieval.search_index_queue",
    "retrieval.search_index_builds",
    "retrieval.documents",
    "retrieval.chunks",
    "proof.retrieval_runs",
    "proof.observability_refs",
    "proof.retrieval_candidates",
    "proof.run_stages",
    "proof.agent_runs",
    "proof.agent_subquestions",
    "proof.agent_retrievals",
    "proof.agent_escalations",
    "proof.agent_answers",
    "proof.answer_citations",
    "proof.evaluation_queries",
    "proof.relevance_judgments",
    "proof.traversal_results",
    "proof.transport_invocations",
)
REQUIRED_FUNCTIONS = (
    ("casework", "queue_evidence"),
    ("retrieval", "acl_visible"),
    ("retrieval", "full_text_search"),
    ("retrieval", "vector_search"),
    ("retrieval", "fuzzy_search"),
    ("retrieval", "hybrid_search"),
    ("retrieval", "assert_search_index_ready"),
    ("retrieval", "configure_ann_runtime"),
    ("retrieval", "traverse_evidence"),
    ("casework", "assert_live_capture_ready"),
    ("casework", "admit_evidence"),
    ("proof", "validate_answer_citations"),
    ("proof", "evaluate_subquestion_coverage"),
    ("proof", "traversal_recall"),
)
REQUIRED_COLUMNS = (
    ("casework", "incidents", "impact_summary"),
    ("casework", "lock_evidence", "relation_oid"),
    ("casework", "lock_evidence", "blocked_lock_mode"),
    ("casework", "lock_evidence", "blocking_lock_mode"),
    ("casework", "pg_stat_activity_samples", "observation_number"),
    ("casework", "pg_lock_samples", "observation_number"),
    ("casework", "pg_blocking_pids_samples", "observation_number"),
    ("proof", "retrieval_runs", "role"),
    ("proof", "retrieval_candidates", "match_tier"),
    ("proof", "retrieval_candidates", "exact_identifier_position"),
    ("proof", "agent_runs", "role"),
    ("proof", "agent_answers", "agent_run_id"),
    ("proof", "agent_answers", "validation_status"),
    ("proof", "transport_invocations", "role"),
)
RETIRED_COLUMNS = (
    ("casework", "incidents", "customer_impact"),
    ("proof", "retrieval_runs", "principal"),
    ("proof", "agent_runs", "principal"),
)
REQUIRED_FUNCTION_SIGNATURES = (
    "retrieval.full_text_search("
    "text,text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer"
    ")",
    "retrieval.vector_search("
    "vector,text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer,integer"
    ")",
    "retrieval.fuzzy_search("
    "text[],real,text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer"
    ")",
    "retrieval.identifier_is_indexed("
    "text[],text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz"
    ")",
    "retrieval.hybrid_search("
    "text,vector,text[],text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer,integer,integer,"
    "numeric,numeric,numeric,real"
    ")",
    "retrieval.traverse_evidence(uuid[],integer,name)",
)
REQUIRED_INDEXES = (
    "retrieval.idx_documents_search_tsv",
    "retrieval.idx_documents_external_key_exact",
    "retrieval.idx_documents_external_key_trgm",
    "retrieval.idx_documents_title_trgm",
    "retrieval.idx_chunks_search_tsv",
    "retrieval.idx_chunks_embedding_hnsw",
)
DEFAULT_FRONTEND_URLS = (
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
)


def version_tuple(value: str | bytes | None) -> tuple[int, ...]:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    match = re.search(r"(\d+(?:\.\d+)*)", value or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


class Doctor:
    def __init__(self) -> None:
        self.hard_failures = 0
        self.warnings = 0

    def ok(self, label: str, detail: str) -> None:
        print(f"[OK]   {label}: {detail}")

    def warn(self, label: str, detail: str) -> None:
        self.warnings += 1
        print(f"[WARN] {label}: {detail}")

    def fail(self, label: str, detail: str, *, hard: bool = True) -> None:
        if not hard:
            self.warn(label, detail)
            return
        self.hard_failures += 1
        print(f"[FAIL] {label}: {detail}")


def _check_catalog_objects(doctor: Doctor, cursor) -> bool:
    missing_tables: list[str] = []
    for name in REQUIRED_TABLES:
        cursor.execute("SELECT to_regclass(%s) AS object", (name,))
        if cursor.fetchone()["object"] is None:
            missing_tables.append(name)
    if missing_tables:
        doctor.fail("schema tables", f"missing {', '.join(missing_tables)}")
        return False
    doctor.ok("schema tables", f"{len(REQUIRED_TABLES)} required tables exist")

    cursor.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE (table_schema, table_name, column_name) IN (
          SELECT required.schema_name, required.table_name, required.column_name
          FROM unnest(%s::text[], %s::text[], %s::text[])
            AS required(schema_name, table_name, column_name)
        )
        """,
        (
            [schema for schema, _, _ in REQUIRED_COLUMNS],
            [table for _, table, _ in REQUIRED_COLUMNS],
            [column for _, _, column in REQUIRED_COLUMNS],
        ),
    )
    present_columns = {
        (row["table_schema"], row["table_name"], row["column_name"])
        for row in cursor.fetchall()
    }
    missing_columns = [
        ".".join(required)
        for required in REQUIRED_COLUMNS
        if required not in present_columns
    ]
    if missing_columns:
        doctor.fail(
            "schema columns",
            f"missing {', '.join(missing_columns)}; run the current core schema migration",
        )
        return False

    cursor.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE (table_schema, table_name, column_name) IN (
          SELECT retired.schema_name, retired.table_name, retired.column_name
          FROM unnest(%s::text[], %s::text[], %s::text[])
            AS retired(schema_name, table_name, column_name)
        )
        """,
        (
            [schema for schema, _, _ in RETIRED_COLUMNS],
            [table for _, table, _ in RETIRED_COLUMNS],
            [column for _, _, column in RETIRED_COLUMNS],
        ),
    )
    retired_columns = [
        ".".join((row["table_schema"], row["table_name"], row["column_name"]))
        for row in cursor.fetchall()
    ]
    if retired_columns:
        doctor.fail(
            "schema columns",
            f"retired {', '.join(retired_columns)} still exist; "
            "run the current core schema migration",
        )
        return False
    doctor.ok(
        "schema columns",
        f"{len(REQUIRED_COLUMNS)} runtime columns present; retired identity columns absent",
    )

    missing_functions: list[str] = []
    for schema, function in REQUIRED_FUNCTIONS:
        cursor.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM pg_proc procedure
              JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
              WHERE namespace.nspname = %s
                AND procedure.proname = %s
            ) AS present
            """,
            (schema, function),
        )
        if not cursor.fetchone()["present"]:
            missing_functions.append(f"{schema}.{function}")
    if missing_functions:
        doctor.fail("schema functions", f"missing {', '.join(missing_functions)}")
        return False
    doctor.ok("schema functions", f"{len(REQUIRED_FUNCTIONS)} required functions exist")

    cursor.execute(
        """
        SELECT signature
        FROM unnest(%s::text[]) AS required(signature)
        WHERE to_regprocedure(signature) IS NULL
        ORDER BY signature
        """,
        (list(REQUIRED_FUNCTION_SIGNATURES),),
    )
    missing_signatures = [row["signature"] for row in cursor.fetchall()]
    if missing_signatures:
        doctor.fail(
            "schema function signatures",
            f"incompatible {', '.join(missing_signatures)}; "
            "run the current core schema migration",
        )
        return False
    doctor.ok(
        "schema function signatures",
        f"{len(REQUIRED_FUNCTION_SIGNATURES)} runtime signatures match",
    )

    missing_indexes: list[str] = []
    for name in REQUIRED_INDEXES:
        cursor.execute("SELECT to_regclass(%s) AS object", (name,))
        if cursor.fetchone()["object"] is None:
            missing_indexes.append(name)
    if missing_indexes:
        doctor.fail("search indexes", f"missing {', '.join(missing_indexes)}")
        return False
    doctor.ok("search indexes", "GIN full-text, GIN trigram, and HNSW indexes exist")
    return True


def _check_casework(doctor: Doctor, cursor, cleared_cursor=None) -> None:
    cursor.execute(
        """
        SELECT source_system, count(*) AS records
        FROM casework.evidence_items
        WHERE NOT is_deleted
        GROUP BY source_system
        ORDER BY source_system
        """,
    )
    sources = cursor.fetchall()
    unexpected = [
        row["source_system"]
        for row in sources
        if row["source_system"] != "pg_incident_capture"
    ]
    if unexpected:
        doctor.fail(
            "live-only evidence",
            "non-live source systems are loaded: " + ", ".join(unexpected),
        )
        return
    if not sources:
        doctor.ok(
            "live-only evidence",
            "schema is empty and awaiting the participant-induced incident",
        )
        return

    cursor.execute(
        """
        SELECT
          incident_evidence_id,
          count(*) FILTER (WHERE wave = 'A') AS wave_a_count,
          count(*) FILTER (WHERE wave = 'B') AS wave_b_count,
          count(*) AS capture_count
        FROM casework.incident_capture_runs
        WHERE capture_origin = 'participant_induced'
        GROUP BY incident_evidence_id
        ORDER BY max(capture_ended_at) DESC
        """
    )
    incidents = cursor.fetchall()
    if len(incidents) != 1:
        doctor.fail(
            "incident capture",
            (
                "expected one participant incident with one or two capture waves, "
                f"found {len(incidents)} incident(s)"
            ),
        )
        return
    incident_group = incidents[0]
    if (
        incident_group["wave_a_count"] != 1
        or incident_group["wave_b_count"] not in (0, 1)
        or incident_group["capture_count"]
        != incident_group["wave_a_count"] + incident_group["wave_b_count"]
    ):
        doctor.fail(
            "incident capture",
            (
                "expected exactly one Wave A and at most one Wave B capture, got "
                f"{dict(incident_group)}"
            ),
        )
        return

    cursor.execute(
        """
        SELECT
          wave_a.capture_id AS wave_a_capture_id,
          wave_a.capture_key AS wave_a_capture_key,
          wave_a.source_bundle_uri AS wave_a_bundle_uri,
          wave_a.engine_version,
          wave_a.relation_oid,
          upper(right(replace(wave_a.capture_id::text, '-', ''), 8))
            AS wave_a_suffix,
          wave_b.capture_id AS wave_b_capture_id,
          wave_b.capture_key AS wave_b_capture_key,
          wave_b.source_bundle_uri AS wave_b_bundle_uri,
          upper(right(replace(wave_b.capture_id::text, '-', ''), 8))
            AS wave_b_suffix,
          incident.external_key AS incident_key
        FROM casework.incident_capture_runs wave_a
        JOIN casework.evidence_items incident
          ON incident.evidence_id = wave_a.incident_evidence_id
        LEFT JOIN casework.incident_capture_runs wave_b
          ON wave_b.incident_evidence_id = wave_a.incident_evidence_id
         AND wave_b.capture_origin = 'participant_induced'
         AND wave_b.wave = 'B'
        WHERE wave_a.incident_evidence_id = %s
          AND wave_a.capture_origin = 'participant_induced'
          AND wave_a.wave = 'A'
        """,
        (incident_group["incident_evidence_id"],),
    )
    capture = cursor.fetchone()
    if capture is None:
        doctor.fail("incident capture", "could not resolve the Wave A capture")
        return

    wave_a_suffix = capture["wave_a_suffix"]
    wave_b_suffix = capture["wave_b_suffix"]
    incident_key = capture["incident_key"]
    unsafe_change_key = f"CHG-{wave_a_suffix}-01"
    analyze_change_key = f"CHG-{wave_a_suffix}-02"
    validation_change_key = (
        f"CHG-{wave_b_suffix}-01" if wave_b_suffix is not None else None
    )
    lock_key = f"LOCK-{wave_a_suffix}-01"
    change_keys = [unsafe_change_key, analyze_change_key]
    if validation_change_key is not None:
        change_keys.append(validation_change_key)
    telemetry_suffixes = [wave_a_suffix]
    if wave_b_suffix is not None:
        telemetry_suffixes.append(wave_b_suffix)
    telemetry_pattern = (
        "^TEL-(" + "|".join(telemetry_suffixes) + ")-[A-Z]+[0-9]+$"
    )

    cursor.execute(
        """
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE evidence_kind = 'incident') AS incidents,
          count(*) FILTER (WHERE evidence_kind = 'change') AS changes,
          count(*) FILTER (WHERE evidence_kind = 'lock_evidence') AS locks,
          count(*) FILTER (WHERE evidence_kind = 'telemetry') AS telemetry,
          bool_and(
            source_uri LIKE %s || '/%%'
            OR (
              %s::text IS NOT NULL
              AND source_uri LIKE %s || '/%%'
            )
          ) AS capture_scoped,
          bool_and(
            CASE evidence_kind
              WHEN 'incident' THEN external_key = %s
              WHEN 'change' THEN external_key = ANY(%s)
              WHEN 'lock_evidence' THEN external_key = %s
              WHEN 'telemetry' THEN external_key ~ %s
              ELSE false
            END
          ) AS run_scoped_keys
        FROM casework.evidence_items
        WHERE source_system = 'pg_incident_capture'
          AND NOT is_deleted
        """,
        (
            capture["wave_a_bundle_uri"],
            capture["wave_b_bundle_uri"],
            capture["wave_b_bundle_uri"],
            incident_key,
            change_keys,
            lock_key,
            telemetry_pattern,
        ),
    )
    evidence = cursor.fetchone()
    cursor.execute(
        """
        SELECT
          array_agg(DISTINCT structured ->> 'phase')
            FILTER (WHERE structured ->> 'phase' IS NOT NULL) AS phases,
          array_agg(DISTINCT telemetry.structured ->> 'telemetry_type')
            FILTER (
              WHERE telemetry.structured ->> 'telemetry_type' IS NOT NULL
            ) AS signal_types
        FROM casework.telemetry_evidence AS telemetry
        WHERE telemetry.capture_id = %s
        """,
        (capture["wave_a_capture_id"],),
    )
    coverage = cursor.fetchone()
    observed_phases = set(coverage["phases"] or ())
    observed_signal_types = set(coverage["signal_types"] or ())
    missing_phases = sorted(set(EXPECTED_INCIDENT_PHASES) - observed_phases)
    missing_signal_types = sorted(
        set(EXPECTED_SIGNAL_TYPES) - observed_signal_types
    )
    expected_low, expected_high = EXPECTED_LIVE_DOCUMENT_RANGE
    volume_detail = (
        f"{evidence['total']} run-derived documents "
        f"({evidence['telemetry']} searchable telemetry documents)"
    )
    if (
        not evidence["capture_scoped"]
        or not evidence["run_scoped_keys"]
        or missing_phases
        or missing_signal_types
    ):
        doctor.fail(
            "live-only evidence",
            (
                f"incident {incident_key} does not satisfy the live corpus contract: "
                f"{dict(evidence)}; missing_phases={missing_phases}; "
                f"missing_signal_types={missing_signal_types}"
            ),
        )
    else:
        doctor.ok(
            "live-only evidence",
            (
                f"incident {incident_key} owns {volume_detail}; "
                "phase and signal coverage complete"
            ),
        )
    if not expected_low <= evidence["total"] <= expected_high:
        doctor.warn(
            "live corpus volume",
            (
                f"{volume_detail}; outside the expected {expected_low}-{expected_high} "
                "document range, which is advisory rather than an acceptance gate"
            ),
        )
    else:
        doctor.ok(
            "live corpus volume",
            (
                f"{volume_detail}; within the expected {expected_low}-{expected_high} "
                "document range (advisory)"
            ),
        )
    try:
        cursor.execute("SELECT casework.assert_live_capture_ready() AS validation")
        validation = cursor.fetchone()["validation"]
        doctor.ok(
            "incident capture",
            (
                f"{capture['wave_a_capture_key']} is participant-induced "
                "live Aurora evidence"
            ),
        )
        if capture["wave_b_capture_id"] is None:
            doctor.ok(
                "two-wave admission",
                "Wave A is indexed; the participant-approved validation is pending",
            )
        elif validation["two_wave_ready"]:
            doctor.ok(
                "two-wave admission",
                (
                    f"{capture['wave_a_capture_key']} + "
                    f"{capture['wave_b_capture_key']} are additive"
                ),
            )
        else:
            doctor.fail(
                "two-wave admission",
                (
                    f"{capture['wave_b_capture_key']} exists but did not satisfy "
                    "the additive validation contract"
                ),
            )
    except Exception as error:
        doctor.fail("incident capture", str(error))


def _check_search_index(doctor: Doctor, cursor) -> None:
    try:
        cursor.execute("SELECT retrieval.assert_search_index_ready() AS health")
        health = cursor.fetchone()["health"]
    except Exception as error:
        doctor.fail("search index", str(error))
        return
    doctor.ok(
        "search index",
        (
            f"documents={health['current_documents']}; "
            f"chunks={health['current_chunks']}; drift={health['drift_issues']}"
        ),
    )
    if health.get("status") == "awaiting_incident":
        doctor.ok(
            "embedding space",
            "none yet; the participant incident has not been admitted",
        )
        return

    settings = get_settings()
    expected_model = (
        "local-hash-embedding-v1"
        if settings.embed_provider == "hash"
        else settings.bedrock_embedding_model
    )
    spaces = health.get("embedding_spaces") or []
    actual_models = {space["embedding_model"] for space in spaces}
    if actual_models != {expected_model}:
        doctor.fail(
            "embedding space",
            f"runtime expects {expected_model}; search index contains {sorted(actual_models)}",
        )
    else:
        doctor.ok("embedding space", f"{expected_model} at 1024 dimensions")


def check_database(doctor: Doctor) -> None:
    settings = get_settings()
    if not settings.database_url:
        doctor.fail("database connectivity", "DATABASE_URL is not set")
        return

    min_postgres = os.environ.get("POSTGRES_MIN_VERSION", "18.3")
    min_pgvector = os.environ.get("PGVECTOR_MIN_VERSION", "0.8.1")
    try:
        # This is a corpus-integrity check, not a participant request. Under the
        # optional RLS module the app-engineer persona intentionally cannot see
        # restricted captured evidence, so using it here would report those rows
        # as missing signal coverage. API health below remains persona-scoped.
        with get_owner_conn(row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_database() AS database_name,
                           current_user AS database_user,
                           current_setting('server_version') AS server_version
                    """
                )
                database = cursor.fetchone()
                doctor.ok(
                    "database connectivity",
                    f"{database['database_name']} as {database['database_user']}",
                )
                server_version = database["server_version"]
                if version_tuple(server_version) < version_tuple(min_postgres):
                    doctor.fail(
                        "PostgreSQL version",
                        f"{server_version}; expected >= {min_postgres}",
                    )
                else:
                    doctor.ok(
                        "PostgreSQL version",
                        f"{server_version} >= {min_postgres}",
                    )

                cursor.execute(
                    """
                    SELECT extname, extversion
                    FROM pg_extension
                    WHERE extname = ANY(%s)
                    """,
                    (list(REQUIRED_EXTENSIONS),),
                )
                extensions = {
                    row["extname"]: row["extversion"] for row in cursor.fetchall()
                }
                missing = [
                    extension
                    for extension in REQUIRED_EXTENSIONS
                    if extension not in extensions
                ]
                if missing:
                    doctor.fail("required extensions", f"missing {', '.join(missing)}")
                    return
                if version_tuple(extensions["vector"]) < version_tuple(min_pgvector):
                    doctor.fail(
                        "pgvector version",
                        f"{extensions['vector']}; expected >= {min_pgvector}",
                    )
                else:
                    doctor.ok(
                        "pgvector version",
                        f"{extensions['vector']} >= {min_pgvector}",
                    )
                doctor.ok(
                    "required extensions",
                    ", ".join(
                        f"{name}={version}"
                        for name, version in sorted(extensions.items())
                    ),
                )

                if not _check_catalog_objects(doctor, cursor):
                    return
                _check_casework(doctor, cursor)
                _check_search_index(doctor, cursor)
    except Exception as error:
        doctor.fail("database connectivity", str(error))


def _check_synthesis_model(doctor: Doctor) -> None:
    settings = get_settings()
    if settings.bedrock_model_transport != "converse_global_cris":
        doctor.fail(
            "Bedrock synthesis transport",
            f"unsupported {settings.bedrock_model_transport}",
        )
        return
    if not settings.bedrock_synthesis_model.startswith(
        ("global.", "us.", "eu.", "apac.")
    ):
        doctor.fail(
            "Bedrock synthesis model",
            "configured ID is not a CRIS inference profile",
        )
        return
    response = get_bedrock_client(
        "bedrock-runtime",
        region=settings.aws_region,
    ).converse(
        modelId=settings.bedrock_synthesis_model,
        messages=[
            {
                "role": "user",
                "content": [{"text": "Reply with exactly READY."}],
            }
        ],
        inferenceConfig={"maxTokens": 16},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict)
    ).strip()
    if not text:
        raise RuntimeError("Bedrock returned an empty synthesis probe")
    doctor.ok(
        "Bedrock synthesis",
        f"{settings.bedrock_synthesis_model} via Converse Global CRIS",
    )


def check_models(doctor: Doctor) -> None:
    settings = get_settings()
    doctor.ok(
        "Bedrock model config",
        (
            f"region={settings.aws_region}; "
            f"embed={settings.bedrock_embedding_model}; "
            f"rerank={settings.cohere_rerank_model}; "
            f"synthesis={settings.bedrock_synthesis_model}"
        ),
    )
    if env_bool("DOCTOR_SKIP_BEDROCK"):
        doctor.warn("Bedrock probes", "skipped by DOCTOR_SKIP_BEDROCK=1")
        return

    if settings.embed_provider == "bedrock":
        try:
            embedding = embed_text(
                "participant-induced relation lock incident",
                provider="bedrock",
                dim=settings.embed_dim,
                input_type="search_query",
            )
            if len(embedding) != settings.embed_dim:
                raise ValueError(
                    f"returned {len(embedding)} dimensions; expected {settings.embed_dim}"
                )
            doctor.ok(
                "Cohere Embed through Bedrock",
                f"{settings.bedrock_embedding_model} returned {len(embedding)} dimensions",
            )
        except Exception as error:
            doctor.fail("Cohere Embed through Bedrock", str(error))
    else:
        doctor.warn(
            "Cohere Embed through Bedrock",
            f"skipped because EMBED_PROVIDER={settings.embed_provider}",
        )

    if settings.cohere_rerank_enabled:
        try:
            results = CohereRerankService().rerank(
                "Which change blocked checkout writes?",
                [
                    "The measured ordinary CREATE INDEX blocked live writers.",
                    "The office lunch menu changed.",
                ],
                top_n=1,
                raise_errors=True,
            )
            if not results or results[0].get("index") != 0:
                raise RuntimeError(f"unexpected rerank response: {results}")
            doctor.ok(
                "Cohere Rerank through Bedrock",
                f"{settings.cohere_rerank_model} ranked the incident evidence first",
            )
        except Exception as error:
            doctor.fail("Cohere Rerank through Bedrock", str(error))
    else:
        doctor.warn("Cohere Rerank through Bedrock", "disabled")

    try:
        _check_synthesis_model(doctor)
    except Exception as error:
        doctor.fail("Bedrock synthesis", str(error))


def check_api_health(doctor: Doctor, require_servers: bool) -> None:
    api_url = (
        os.environ.get("DOCTOR_API_URL")
        or os.environ.get("RETRIEVAL_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
    try:
        response = requests.get(f"{api_url}/ready", timeout=3)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") not in {"ready", "awaiting_incident"}:
            raise RuntimeError(f"unexpected readiness payload: {payload}")
        doctor.ok(
            "API readiness",
            f"{api_url}/ready returned {payload.get('status')}",
        )
    except Exception as error:
        doctor.fail(
            "API readiness",
            f"{api_url}/ready unavailable: {error}",
            hard=require_servers,
        )


def check_frontend_health(doctor: Doctor, require_servers: bool) -> None:
    configured = os.environ.get("DOCTOR_FRONTEND_URL")
    urls = [configured] if configured else list(DEFAULT_FRONTEND_URLS)
    failures: list[str] = []
    for url in [value for value in urls if value]:
        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            doctor.ok("frontend health", f"{url} returned HTTP {response.status_code}")
            return
        except Exception as error:
            failures.append(f"{url}: {error}")
    doctor.fail("frontend health", "; ".join(failures), hard=require_servers)


def main() -> int:
    doctor = Doctor()
    require_servers = env_bool("DOCTOR_REQUIRE_SERVERS")
    try:
        check_database(doctor)
        check_models(doctor)
        check_api_health(doctor, require_servers)
        check_frontend_health(doctor, require_servers)
    finally:
        close_pool()

    if doctor.hard_failures:
        print(
            f"\nDoctor failed: {doctor.hard_failures} hard failure(s), "
            f"{doctor.warnings} warning(s)."
        )
        return 1
    print(f"\nDoctor passed with {doctor.warnings} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
