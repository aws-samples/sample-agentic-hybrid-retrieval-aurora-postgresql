#!/usr/bin/env python3
"""Time an HNSW build on the served catalog without touching its serving index.

The build creates a benchmark-owned index with the production `m` and
`ef_construction` on the same physical table, records the session's worker and
memory settings and the resulting size, and drops the index unless asked to
keep it. The serving index is never dropped or rebuilt, so retrieval keeps
working while the measurement runs. A plain `CREATE INDEX` holds a SHARE lock
on the table for the duration, which blocks writes but not reads; run this on
a cluster nobody is importing into.

Usage
-----
    make benchmark-index-build
    uv run python scripts/benchmark_index_build.py --workers 7 \\
        --maintenance-work-mem 8GB --repeat 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from psycopg import sql

from scripts.retrieval_profile import explain, load_profile
from service.catalog_runtime import active_dataset, catalog_indexes
from service.config import get_settings
from service.hnsw_corpus import corpus_manifest

OUTPUT = REPO / "data" / "benchmarks" / "hnsw_index_build.json"
BENCH_SUFFIX = "_bench"
RECORDED_SETTINGS = (
    "maintenance_work_mem",
    "max_parallel_maintenance_workers",
    "max_parallel_workers",
    "max_worker_processes",
    "shared_buffers",
    "work_mem",
)


def bench_index_name() -> str:
    """The benchmark-owned index name, derived from the serving index's name."""
    return catalog_indexes().fp32 + BENCH_SUFFIX


def build_once(
    connection: Any,
    *,
    workers: int | None,
    maintenance_work_mem: str | None,
    keep: bool,
) -> dict[str, Any]:
    """Build the benchmark index once and return the timed record.

    The settings are applied on this session only and read back from
    `pg_settings` after being applied, so the record states what the server
    used rather than what was requested.
    """
    indexes = catalog_indexes()
    profile = load_profile()
    name = bench_index_name()
    connection.execute(
        sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(indexes.schema, name))
    )
    if workers is not None:
        connection.execute(
            sql.SQL("SET max_parallel_maintenance_workers = {}").format(
                sql.Literal(workers)
            )
        )
    if maintenance_work_mem is not None:
        connection.execute(
            sql.SQL("SET maintenance_work_mem = {}").format(
                sql.Literal(maintenance_work_mem)
            )
        )
    settings = {
        row["name"]: {"setting": row["setting"], "unit": row["unit"]}
        for row in connection.execute(
            "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
            (list(RECORDED_SETTINGS),),
        ).fetchall()
    }
    statement = (
        sql.SQL(
            "CREATE INDEX {} ON {} USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = {}, ef_construction = {})"
        )
        .format(
            sql.Identifier(name),
            sql.Identifier(indexes.schema, indexes.table),
            sql.Literal(profile.hnsw_m),
            sql.Literal(profile.hnsw_ef_construction),
        )
        .as_string(None)
    )
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    connection.execute(statement)
    elapsed = time.perf_counter() - started
    size = connection.execute(
        "SELECT pg_relation_size(%s::regclass) AS bytes",
        (f"{indexes.schema}.{name}",),
    ).fetchone()["bytes"]
    record = {
        "index": f"{indexes.schema}.{name}",
        "statement": statement,
        "started_at": started_at.isoformat(),
        "seconds": round(elapsed, 2),
        "size_bytes": int(size),
        "settings": settings,
        "kept": keep,
    }
    if not keep:
        connection.execute(
            sql.SQL("DROP INDEX {}").format(sql.Identifier(indexes.schema, name))
        )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, help="max_parallel_maintenance_workers")
    parser.add_argument("--maintenance-work-mem", help="for example 8GB")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--keep", action="store_true", help="leave the last index in place"
    )
    parser.add_argument("--label", default="")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    if arguments.repeat < 1 or (
        arguments.workers is not None and arguments.workers < 0
    ):
        raise SystemExit(
            explain(
                "non-positive --repeat or negative --workers", "pass positive values"
            )
        )
    import psycopg
    from psycopg.rows import dict_row

    settings = get_settings()
    instance_class = settings.aurora_instance_class
    if not instance_class:
        raise SystemExit(
            explain(
                "AURORA_INSTANCE_CLASS is empty",
                "set it to the connected Aurora instance class",
            )
        )
    runs = []
    with psycopg.connect(
        settings.database_url, autocommit=True, row_factory=dict_row
    ) as connection:
        connection.execute("SET application_name = 'mosaic-index-build-benchmark'")
        environment = dict(
            connection.execute(
                "SELECT aurora_db_instance_identifier() AS database_instance_id, "
                "current_setting('server_version') AS database_version, "
                "(SELECT extversion FROM pg_extension WHERE extname = 'vector') "
                "AS vector_extension_version, "
                "count(*) FILTER (WHERE embedding IS NOT NULL) AS vector_count "
                f"FROM {catalog_indexes().qualified_table}"
            ).fetchone()
        )
        manifest = corpus_manifest(connection)
        for attempt in range(arguments.repeat):
            keep = arguments.keep and attempt == arguments.repeat - 1
            record = build_once(
                connection,
                workers=arguments.workers,
                maintenance_work_mem=arguments.maintenance_work_mem,
                keep=keep,
            )
            runs.append(record)
            print(
                f"build {attempt + 1}/{arguments.repeat}: {record['seconds']} s, "
                f"{record['size_bytes']} bytes, {record['settings']}",
                flush=True,
            )
    payload = {
        "kind": "measured",
        "measured_at": datetime.now(UTC).isoformat(),
        "label": arguments.label,
        "provenance": {
            "source_revision": settings.source_revision,
            "source_worktree_dirty": settings.source_worktree_dirty,
            "dataset_id": active_dataset(),
            "dataset_manifest_sha256": manifest,
            "instance_class": instance_class,
            **environment,
            "command": " ".join(sys.argv),
            "method": (
                "one plain CREATE INDEX per run on the served catalog's physical "
                "table, benchmark-owned name, production m and ef_construction, "
                "session settings read back from pg_settings; the serving index "
                "is untouched; wall clock measured from the client"
            ),
        },
        "runs": runs,
    }
    existing = (
        json.loads(arguments.output.read_text()) if arguments.output.exists() else {}
    )
    history = existing.get("history", [])
    if existing.get("runs"):
        history.append({k: v for k, v in existing.items() if k != "history"})
    payload["history"] = history
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"wrote {arguments.output}")


if __name__ == "__main__":
    main()
