#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import get_dict_conn  # noqa: E402
from app.embeddings import embed_text  # noqa: E402
from app.rerank import CohereRerankService  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "seed" / "artifacts" / "manifest.json"
REQUIRED_EXTENSIONS = ["vector", "pg_trgm", "btree_gin", "pgcrypto", "pg_stat_statements"]
REQUIRED_TABLES = [
    "ops.source_objects",
    "ops.object_chunks",
    "ops.retrieval_runs",
    "ops.retrieval_candidates",
    "ops.agent_answers",
    "ops.retrieval_run_metrics",
]
REQUIRED_FUNCTIONS = ["hybrid_search", "to_or_tsquery", "rrf"]
DEFAULT_FRONTEND_URLS = [
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "http://127.0.0.1:5177",
]


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        if hard:
            self.hard_failures += 1
            print(f"[FAIL] {label}: {detail}")
        else:
            self.warn(label, detail)


def load_manifest(doctor: Doctor) -> dict[str, Any] | None:
    if not MANIFEST_PATH.exists():
        doctor.fail("seed manifest", f"missing {MANIFEST_PATH.relative_to(ROOT)}")
        return None
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        doctor.fail("seed manifest", f"could not parse manifest.json: {exc}")
        return None
    doctor.ok("seed manifest", f"{manifest.get('version')} with {manifest.get('total_objects')} objects")
    return manifest


def check_seed_artifact(doctor: Doctor, manifest: dict[str, Any] | None) -> None:
    if not manifest:
        return
    artifact_name = manifest.get("artifact")
    if not artifact_name:
        doctor.fail("seed artifact", "manifest has no artifact field")
        return
    artifact_path = MANIFEST_PATH.parent / artifact_name
    if not artifact_path.exists():
        doctor.fail("seed artifact", f"missing {artifact_path.relative_to(ROOT)}")
        return
    actual = sha256_file(artifact_path)
    expected = manifest.get("artifact_sha256")
    size_mb = artifact_path.stat().st_size / (1024 * 1024)
    if expected and actual != expected:
        doctor.fail("seed hash", f"{artifact_name} SHA256 {actual} does not match manifest {expected}")
        return
    suffix = "matches manifest" if expected else "recorded; manifest has no artifact_sha256"
    doctor.ok("seed hash", f"{actual} ({size_mb:.1f} MiB, {suffix})")


def check_database(doctor: Doctor, manifest: dict[str, Any] | None) -> None:
    settings = get_settings()
    if not settings.database_url:
        doctor.fail("Aurora connectivity", "DATABASE_URL is not set")
        return

    min_postgres = os.environ.get("POSTGRES_MIN_VERSION", "18.3")
    min_pgvector = os.environ.get("PGVECTOR_MIN_VERSION", "0.8.1")

    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database() AS db, current_user AS user, version() AS version")
                db = cur.fetchone()
                cur.execute("SHOW server_version")
                server_version = cur.fetchone()["server_version"]
                doctor.ok("Aurora connectivity", f"connected to {db['db']} as {db['user']}")
                if version_tuple(server_version) < version_tuple(min_postgres):
                    doctor.fail("PostgreSQL version", f"{server_version}; expected >= {min_postgres}")
                else:
                    doctor.ok("PostgreSQL version", f"{server_version} >= {min_postgres}")

                cur.execute(
                    "SELECT extname, extversion FROM pg_extension WHERE extname = ANY(%s)",
                    (REQUIRED_EXTENSIONS,),
                )
                extensions = {row["extname"]: row["extversion"] for row in cur.fetchall()}
                missing = [name for name in REQUIRED_EXTENSIONS if name not in extensions]
                if missing:
                    doctor.fail("required extensions", f"missing {', '.join(missing)}")
                else:
                    vector_version = extensions["vector"]
                    if version_tuple(vector_version) < version_tuple(min_pgvector):
                        doctor.fail("pgvector version", f"{vector_version}; expected >= {min_pgvector}")
                    else:
                        doctor.ok("pgvector version", f"{vector_version} >= {min_pgvector}")
                    doctor.ok("required extensions", ", ".join(f"{k}={v}" for k, v in sorted(extensions.items())))

                for table_name in REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s) AS name", (table_name,))
                    if cur.fetchone()["name"] is None:
                        doctor.fail("schema tables", f"missing {table_name}")
                        return
                doctor.ok("schema tables", f"{len(REQUIRED_TABLES)} required ops tables exist")

                cur.execute(
                    """
                    SELECT proname
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'ops' AND proname = ANY(%s)
                    """,
                    (REQUIRED_FUNCTIONS,),
                )
                functions = {row["proname"] for row in cur.fetchall()}
                missing_functions = [name for name in REQUIRED_FUNCTIONS if name not in functions]
                if missing_functions:
                    doctor.fail("schema functions", f"missing ops.{', ops.'.join(missing_functions)}")
                else:
                    doctor.ok("schema functions", ", ".join(f"ops.{name}" for name in sorted(functions)))

                if manifest:
                    check_seed_rows(doctor, cur, manifest)
    except Exception as exc:
        doctor.fail("Aurora connectivity", str(exc))


def check_seed_rows(doctor: Doctor, cur, manifest: dict[str, Any]) -> None:
    cur.execute("SELECT count(*) AS count FROM ops.source_objects")
    object_count = int(cur.fetchone()["count"])
    expected_total = int(manifest.get("total_objects") or 0)
    if object_count != expected_total:
        doctor.fail("seed rows", f"ops.source_objects has {object_count}; expected {expected_total}")
        return

    cur.execute("SELECT source_system, count(*) AS count FROM ops.source_objects GROUP BY source_system")
    actual_per_system = {row["source_system"]: int(row["count"]) for row in cur.fetchall()}
    expected_per_system = manifest.get("per_system") or {}
    mismatches = [
        f"{system}={actual_per_system.get(system, 0)} expected {count}"
        for system, count in expected_per_system.items()
        if actual_per_system.get(system, 0) != int(count)
    ]
    if mismatches:
        doctor.fail("seed distribution", "; ".join(mismatches))
    else:
        doctor.ok("seed distribution", ", ".join(f"{k}={v}" for k, v in sorted(actual_per_system.items())))

    canonical_question = manifest.get("canonical_question", "Why did Orion slip?")
    cur.execute(
        """
        SELECT run_id, confidence, source_count, system_count
        FROM ops.agent_answers
        WHERE question = %s OR question_norm = lower(%s)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (canonical_question, canonical_question),
    )
    answer = cur.fetchone()
    if not answer:
        doctor.fail("canonical answer", f"missing ops.agent_answers row for {canonical_question!r}")
    else:
        doctor.ok(
            "canonical answer",
            f"run {str(answer['run_id'])[-8:]} confidence={float(answer['confidence']):.2f} sources={answer['source_count']}",
        )

    cur.execute("SELECT count(*) AS count FROM ops.object_chunks WHERE embedding IS NOT NULL")
    embedded_chunks = int(cur.fetchone()["count"])
    if embedded_chunks <= 0:
        doctor.fail("seed embeddings", "no embedded chunks found")
    else:
        doctor.ok("seed embeddings", f"{embedded_chunks} chunks have vectors")


def check_models(doctor: Doctor) -> None:
    settings = get_settings()
    doctor.ok(
        "Bedrock model config",
        (
            f"region={settings.aws_region}; embed={settings.bedrock_embedding_model}; "
            f"router={settings.bedrock_router_model}; synth={settings.bedrock_opus_model}; "
            f"cohere_rerank={settings.cohere_rerank_model}; claude_code={settings.claude_code_model}"
        ),
    )

    if settings.embed_provider == "bedrock":
        try:
            embedding = embed_text(
                "doctor Orion retrieval query",
                provider="bedrock",
                dim=settings.embed_dim,
                input_type="search_query",
            )
        except Exception as exc:
            doctor.fail("Cohere Embed via Bedrock", str(exc))
        else:
            if len(embedding) != settings.embed_dim:
                doctor.fail("Cohere Embed via Bedrock", f"returned {len(embedding)} dims; expected {settings.embed_dim}")
            else:
                doctor.ok("Cohere Embed via Bedrock", f"{settings.bedrock_embedding_model} returned {len(embedding)} dims")
    else:
        doctor.warn("Cohere Embed via Bedrock", f"skipped because EMBED_PROVIDER={settings.embed_provider}")

    if settings.cohere_rerank_enabled:
        try:
            results = CohereRerankService().rerank(
                "Why did Orion slip?",
                [
                    "Orion slipped because the export worker fix missed the release gate.",
                    "Unrelated office catering policy and parking reminder.",
                ],
                top_n=1,
                raise_errors=True,
            )
        except Exception as exc:
            doctor.fail("Cohere Rerank via Bedrock", str(exc))
        else:
            if not results:
                doctor.fail("Cohere Rerank via Bedrock", "rerank returned no results")
            else:
                top = results[0]
                score = float(top.get("relevance_score") or 0.0)
                doctor.ok(
                    "Cohere Rerank via Bedrock",
                    f"{settings.cohere_rerank_model} top_index={top.get('index')} score={score:.3f}",
                )
    else:
        doctor.warn("Cohere Rerank via Bedrock", "disabled by COHERE_RERANK_ENABLED=0")


def check_api_health(doctor: Doctor, require_servers: bool) -> None:
    api_url = (
        os.environ.get("DOCTOR_API_URL")
        or os.environ.get("RETRIEVAL_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
    try:
        resp = requests.get(f"{api_url}/health", timeout=3)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is True:
            doctor.ok("API health", f"{api_url}/health returned ok")
        else:
            doctor.fail("API health", f"{api_url}/health returned {payload}", hard=require_servers)
    except Exception as exc:
        doctor.fail("API health", f"{api_url}/health unavailable: {exc}", hard=require_servers)


def check_frontend_health(doctor: Doctor, require_servers: bool) -> None:
    configured = os.environ.get("DOCTOR_FRONTEND_URL")
    urls = [configured] if configured else DEFAULT_FRONTEND_URLS
    failures: list[str] = []
    for url in [u for u in urls if u]:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code >= 400:
                failures.append(f"{url} HTTP {resp.status_code}")
                continue
            doctor.ok("frontend health", f"{url} returned HTTP {resp.status_code}")
            return
        except Exception as exc:
            failures.append(f"{url} unavailable: {exc}")
    doctor.fail("frontend health", "; ".join(failures), hard=require_servers)


def main() -> int:
    doctor = Doctor()
    require_servers = env_bool("DOCTOR_REQUIRE_SERVERS", False)
    manifest = load_manifest(doctor)
    check_seed_artifact(doctor, manifest)
    check_database(doctor, manifest)
    check_models(doctor)
    check_api_health(doctor, require_servers)
    check_frontend_health(doctor, require_servers)

    if doctor.hard_failures:
        print(f"\nDoctor failed: {doctor.hard_failures} hard failure(s), {doctor.warnings} warning(s).")
        return 1
    print(f"\nDoctor passed with {doctor.warnings} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
