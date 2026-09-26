#!/usr/bin/env python3
"""Build the halfvec and binary HNSW indexes on the served catalog's table.

The Scale & HNSW instrument compares three representations of the same
vectors: the fp32 column, a `halfvec` cast of it and its binary quantization.
The two quantized indexes are expression indexes over the fp32 column, so no
row changes and nothing is re-embedded. They are named by
`service.catalog_runtime.catalog_indexes()`, which is how the probe,
`make benchmark-hnsw` and the representation gate find them.

By default the builds are plain `CREATE INDEX` statements, which hold a
SHARE lock that blocks writes but not reads for the duration (a few minutes
each with parallel workers). Pass `--concurrently` on a cluster that is being
written to; the build then takes longer and cannot use parallel workers.

Usage
-----
    make db-index-quantized-catalog
    uv run python scripts/build_quantized_indexes.py --workers 7 \\
        --maintenance-work-mem 8GB
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
from service.db import index_states_on

DEFINITIONS = {
    "halfvec": ("(embedding::halfvec(1024))", "halfvec_cosine_ops"),
    "binary": ("(binary_quantize(embedding)::bit(1024))", "bit_hamming_ops"),
}
SETTING_NAMES = ("maintenance_work_mem", "max_parallel_maintenance_workers")


def session_settings(connection: Any) -> dict[str, dict[str, str | None]]:
    """The build settings as the server reports them, so the record states what ran."""
    rows = connection.execute(
        "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
        (list(SETTING_NAMES),),
    ).fetchall()
    return {
        row["name"]: {"setting": row["setting"], "unit": row["unit"]} for row in rows
    }


def build_statement(representation: str, *, concurrently: bool) -> sql.Composed:
    """The CREATE INDEX for one quantized representation on the served catalog."""
    indexes = catalog_indexes()
    profile = load_profile()
    expression, operator_class = DEFINITIONS[representation]
    name = {"halfvec": indexes.halfvec, "binary": indexes.binary}[representation]
    return sql.SQL(
        "CREATE INDEX {concurrently}IF NOT EXISTS {name} ON {table} "
        "USING hnsw ({expression} {operator_class}) "
        "WITH (m = {m}, ef_construction = {ef_construction})"
    ).format(
        concurrently=sql.SQL("CONCURRENTLY " if concurrently else ""),
        name=sql.Identifier(name),
        table=sql.Identifier(indexes.schema, indexes.table),
        expression=sql.SQL(expression),
        operator_class=sql.SQL(operator_class),
        m=sql.Literal(profile.hnsw_m),
        ef_construction=sql.Literal(profile.hnsw_ef_construction),
    )


def build(
    connection: Any,
    *,
    representations: list[str],
    workers: int | None,
    maintenance_work_mem: str | None,
    concurrently: bool,
) -> list[dict[str, Any]]:
    """Build each requested index that is not already usable; return the records."""
    indexes = catalog_indexes()
    names = {"halfvec": indexes.halfvec, "binary": indexes.binary}
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
    settings = session_settings(connection)
    records = []
    for representation in representations:
        name = names[representation]
        state = index_states_on(connection, [name], schema=indexes.schema)[name]
        if state == "invalid":
            connection.execute(
                sql.SQL("DROP INDEX {}").format(sql.Identifier(indexes.schema, name))
            )
        if state == "valid":
            records.append(
                {
                    "representation": representation,
                    "index": name,
                    "state": "already valid",
                }
            )
            print(f"{name}: already valid", flush=True)
            continue
        statement = build_statement(representation, concurrently=concurrently)
        started = time.perf_counter()
        connection.execute(statement)
        seconds = round(time.perf_counter() - started, 2)
        size = connection.execute(
            "SELECT pg_relation_size(%s::regclass) AS bytes",
            (f"{indexes.schema}.{name}",),
        ).fetchone()["bytes"]
        records.append(
            {
                "representation": representation,
                "index": name,
                "state": "built",
                "seconds": seconds,
                "size_bytes": int(size),
                "statement": statement.as_string(None),
                "settings": settings,
            }
        )
        print(f"{name}: built in {seconds} s, {size} bytes", flush=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representation", choices=sorted(DEFINITIONS), nargs="+")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--maintenance-work-mem")
    parser.add_argument("--concurrently", action="store_true")
    parser.add_argument("--report", type=Path, help="Write the build records as JSON")
    arguments = parser.parse_args()
    if arguments.workers is not None and arguments.workers < 0:
        raise SystemExit(explain("negative --workers", "pass zero or more workers"))
    import psycopg
    from psycopg.rows import dict_row

    settings = get_settings()
    with psycopg.connect(
        settings.database_url, autocommit=True, row_factory=dict_row
    ) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET application_name = 'mosaic-quantized-index-build'")
        records = build(
            connection,
            representations=arguments.representation or ["halfvec", "binary"],
            workers=arguments.workers,
            maintenance_work_mem=arguments.maintenance_work_mem,
            concurrently=arguments.concurrently,
        )
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(
            json.dumps(
                {
                    "built_at": datetime.now(UTC).isoformat(),
                    "dataset_id": active_dataset() or "synthetic-legacy",
                    "source_revision": settings.source_revision,
                    "command": "scripts/build_quantized_indexes.py "
                    + " ".join(sys.argv[1:]),
                    "records": records,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
