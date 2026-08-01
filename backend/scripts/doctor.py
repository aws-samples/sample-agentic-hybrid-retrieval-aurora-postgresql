#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bedrock import get_bedrock_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import close_pool, get_dict_conn  # noqa: E402
from app.embeddings import embed_text  # noqa: E402
from app.rerank import CohereRerankService  # noqa: E402

REQUIRED_EXTENSIONS = ("vector", "pg_trgm", "pg_stat_statements")
REQUIRED_TABLES = (
    "casework.database_clusters",
    "casework.evidence_items",
    "casework.incidents",
    "casework.changes",
    "casework.support_cases",
    "casework.runbooks",
    "casework.fixture_captures",
    "casework.lock_evidence",
    "casework.pg_stat_activity_samples",
    "casework.pg_lock_samples",
    "casework.pg_blocking_pids_samples",
    "casework.pg_stat_statements_samples",
    "casework.cloudwatch_metric_samples",
    "casework.database_insights_samples",
    "casework.customer_commitments",
    "casework.postmortems",
    "casework.change_runbooks",
    "casework.support_case_commitments",
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
    ("casework", "assert_release_capture_ready"),
    ("proof", "validate_answer_citations"),
    ("proof", "evaluate_subquestion_coverage"),
    ("proof", "traversal_recall"),
)
REQUIRED_COLUMNS = (
    ("casework", "lock_evidence", "relation_oid"),
    ("casework", "lock_evidence", "blocked_lock_mode"),
    ("casework", "lock_evidence", "blocking_lock_mode"),
    ("proof", "retrieval_runs", "role"),
    ("proof", "retrieval_candidates", "match_tier"),
    ("proof", "retrieval_candidates", "exact_identifier_position"),
    ("proof", "agent_runs", "role"),
    ("proof", "agent_answers", "agent_run_id"),
    ("proof", "agent_answers", "validation_status"),
    ("proof", "transport_invocations", "role"),
)
RETIRED_COLUMNS = (
    ("proof", "retrieval_runs", "principal"),
    ("proof", "agent_runs", "principal"),
)
REQUIRED_FUNCTION_SIGNATURES = (
    "retrieval.full_text_search("
    "text,text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer"
    ")",
    "retrieval.vector_search("
    "vector,text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer,integer"
    ")",
    "retrieval.fuzzy_search("
    "text[],real,text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz,integer"
    ")",
    "retrieval.identifier_is_indexed("
    "text[],text[],text,text,text,text[],text,text,text,text,"
    "timestamptz,timestamptz"
    ")",
    "retrieval.hybrid_search("
    "text,vector,text[],text[],text,text,text,text[],text,text,text,text,"
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
CANONICAL_KEYS = (
    "INC-2047",
    "CHG-1842",
    "CASE-7419",
    "RB-017",
    "LOCK-2047-001",
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
    security_enabled = get_settings().workbench_security_enabled
    cursor.execute(
        """
        SELECT external_key
        FROM casework.evidence_items
        WHERE external_key = ANY(%s)
          AND NOT is_deleted
        """,
        (list(CANONICAL_KEYS),),
    )
    present = {row["external_key"] for row in cursor.fetchall()}
    missing = [key for key in CANONICAL_KEYS if key not in present]
    if missing:
        doctor.fail("canonical casework", f"missing {', '.join(missing)}")
    else:
        doctor.ok("canonical casework", ", ".join(CANONICAL_KEYS))

    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM casework.incident_changes) AS incident_changes,
          (SELECT count(*) FROM casework.incident_support_cases) AS incident_cases,
          (SELECT count(*) FROM casework.incident_runbooks) AS incident_runbooks
        """
    )
    relations = cursor.fetchone()
    if not all(int(value) > 0 for value in relations.values()):
        doctor.fail("canonical relationships", json.dumps(relations))
    else:
        doctor.ok(
            "canonical relationships",
            ", ".join(f"{name}={value}" for name, value in relations.items()),
        )

    if security_enabled:
        if cleared_cursor is None:
            raise RuntimeError("security mode requires a cleared persona cursor")
        cursor.execute(
            """
            SELECT count(*) AS visible
            FROM casework.evidence_items
            WHERE external_key = 'CASE-7421'
              AND NOT is_deleted
            """
        )
        app_engineer_visible = int(cursor.fetchone()["visible"])
        if app_engineer_visible:
            doctor.fail(
                "ACL enforcement",
                "App Engineer can read CASE-7421; restricted evidence is leaking",
            )
        else:
            doctor.ok("ACL enforcement", "CASE-7421 hidden from App Engineer")
    else:
        cursor.execute(
            """
            SELECT count(*) AS visible
            FROM retrieval.full_text_search('CASE-7421', p_limit => 50)
            WHERE external_key = 'CASE-7421'
            """
        )
        visible = int(cursor.fetchone()["visible"])
        if visible:
            doctor.fail(
                "ACL enforcement",
                "core retrieval returned CASE-7421 to App Engineer",
            )
        else:
            doctor.ok(
                "ACL enforcement",
                "core retrieval predicate hides CASE-7421 from App Engineer",
            )
        doctor.ok(
            "security mode",
            "core retrieval; optional RLS and masking checks are not required",
        )

    fixture_cursor = cleared_cursor if security_enabled else cursor
    fixture_cursor.execute(
        """
        SELECT external_key,
               coalesce(acl ->> 'visibility', 'restricted') AS visibility
        FROM casework.evidence_items
        WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
          AND NOT is_deleted
        ORDER BY external_key
        """
    )
    restricted = fixture_cursor.fetchall()
    restricted_keys = [row["external_key"] for row in restricted]
    if "CASE-7421" not in restricted_keys:
        doctor.fail(
            "ACL fixture",
            "CASE-7421 is not marked restricted; run the current core schema "
            "migration or reseed",
        )
    elif security_enabled and len(restricted_keys) < 2:
        doctor.fail(
            "ACL fixture",
            "only CASE-7421 is restricted; reseed to load the optional "
            "security cohort",
        )
    else:
        doctor.ok(
            "ACL fixture",
            f"{len(restricted_keys)} restricted evidence item(s) "
            f"({', '.join(restricted_keys)})",
        )

    cursor.execute(
        """
        SELECT capture_mode, capture_key, engine_version, relation_oid
        FROM casework.fixture_captures
        ORDER BY capture_started_at DESC
        LIMIT 1
        """
    )
    capture = cursor.fetchone()
    require_release = env_bool("DOCTOR_REQUIRE_RELEASE_CAPTURE")
    if not capture:
        doctor.fail("incident capture", "no genuine capture bundle is loaded")
    elif capture["capture_mode"] == "release_aurora":
        try:
            cursor.execute(
                "SELECT casework.assert_release_capture_ready() AS validation"
            )
            cursor.fetchone()
            doctor.ok(
                "incident capture",
                f"{capture['capture_key']} is release-ready Aurora evidence",
            )
        except Exception as error:
            doctor.fail("incident capture", str(error))
    elif require_release:
        doctor.fail(
            "incident capture",
            (
                f"{capture['capture_key']} is offline_test; "
                "release_aurora evidence is required"
            ),
        )
    else:
        doctor.ok(
            "incident capture",
            (
                f"{capture['capture_key']} is genuine offline_test evidence "
                "and does not satisfy the Aurora release gate"
            ),
        )


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
        with get_dict_conn("app_engineer") as connection:
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
                if settings.workbench_security_enabled:
                    with get_dict_conn("dba") as cleared_connection:
                        with cleared_connection.cursor() as cleared_cursor:
                            _check_casework(doctor, cursor, cleared_cursor)
                else:
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
                "CHG-1842 relation lock incident",
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
                    "CHG-1842 ran CREATE INDEX and blocked writes.",
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
        if payload.get("status") != "ready":
            raise RuntimeError(f"unexpected readiness payload: {payload}")
        doctor.ok("API readiness", f"{api_url}/ready returned ready")
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
