#!/usr/bin/env python3
"""Restore source-bound vocabulary caches, or rebuild from the production SQL.

The cache contains derived rows, never embeddings. Its release contract binds
every byte to the exact projection inputs, PostgreSQL text parser and production
procedure. Export recomputes both vocabularies in session-local tables first.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stage_real_catalog import validate_dsn

CONTRACT = ROOT / "db/config/corpus-vocabulary-cache.json"
SCHEMAS = ("mosaic_search", "mosaic_live_search")
TABLES = ("corpus_lexeme", "corpus_surface_lexeme")
INPUT_COLUMNS = (
    "product_id, search_document, title_text, identity_text, feature_text, "
    "body_text, trigram_text"
)


def procedure_sql() -> str:
    """Read the production procedure rather than duplicate its tokenization."""
    source = (ROOT / "db/sql/20_query_coverage.sql").read_text()
    start = source.index(
        "CREATE OR REPLACE PROCEDURE mosaic_search.refresh_corpus_lexeme()"
    )
    return source[start:].split("\n$$;", 1)[0] + "\n$$;"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def environment_identity(connection) -> dict:
    """Pin the parser version and the dictionaries used by the surface SQL."""
    version, encoding, dictionaries = connection.execute("""
        SELECT current_setting('server_version_num'), current_setting('server_encoding'),
          (SELECT jsonb_agg(jsonb_build_array(m.maptokentype, m.mapseqno,
                     n.nspname, d.dictname, d.dictinitoption) ORDER BY m.maptokentype, m.mapseqno)
           FROM pg_ts_config_map m JOIN pg_ts_dict d ON d.oid=m.mapdict
           JOIN pg_namespace n ON n.oid=d.dictnamespace
           WHERE m.mapcfg='pg_catalog.simple'::regconfig)
    """).fetchone()
    return {
        "server_version_num": version,
        "encoding": encoding,
        "simple_dictionaries": dictionaries,
    }


def fingerprint(connection, schema: str) -> dict:
    """Hash only the production procedure's inputs, in stable product order."""
    if schema not in SCHEMAS:
        raise ValueError(
            f"Vocabulary schema rule: found {schema!r}; use one of {SCHEMAS}."
        )
    count, checksum = connection.execute(f"""
        SELECT count(*), encode(sha256(convert_to(string_agg(
          encode(sha256(convert_to(ROW(product_id, search_document::text,
            title_text, identity_text, feature_text, body_text, trigram_text)::text,
            'UTF8')), 'hex'), '' ORDER BY product_id), 'UTF8')), 'hex')
        FROM {schema}.product_document
    """).fetchone()
    return {"products": count, "sha256": checksum}


def verify_contract(contract: dict) -> None:
    """Check source-to-cache agreement even when ignored assets are absent in CI."""
    actual = hashlib.sha256(procedure_sql().encode()).hexdigest()
    schemas = set(contract.get("schemas", {}))
    if (
        contract.get("schema_version") != 1
        or not schemas
        or not schemas.issubset(SCHEMAS)
    ):
        raise ValueError(
            f"Vocabulary contract rule: found version={contract.get('schema_version')!r}, schemas={sorted(contract.get('schemas', {}))}; regenerate the complete cache."
        )
    if contract.get("procedure_sha256") != actual:
        raise ValueError(
            f"Vocabulary SQL rule: found procedure {actual}; regenerate the cache with the current production SQL."
        )
    for schema in contract["schemas"]:
        tables = contract["schemas"][schema]["tables"]
        if set(tables) != set(TABLES):
            raise ValueError(
                f"Vocabulary tables rule: found {sorted(tables)}; export both vocabularies for {schema}."
            )


def verify_files(directory: Path, contract: dict, *, schema: str | None = None) -> None:
    """Reject missing, changed or stale assets before opening the database."""
    verify_contract(contract)
    if schema is not None and schema not in contract["schemas"]:
        raise ValueError(
            f"Vocabulary schema rule: {schema!r} is absent from the contract; export that catalog's cache first."
        )
    selected_schemas = (schema,) if schema else contract["schemas"]
    for selected_schema in selected_schemas:
        tables = contract["schemas"][selected_schema]["tables"]
        for table in TABLES:
            path = directory / f"{selected_schema}.{table}.csv.gz"
            expected = tables[table]
            actual = digest(path) if path.is_file() else "missing"
            size = path.stat().st_size if path.is_file() else None
            if actual != expected["sha256"] or size != expected["bytes"]:
                raise ValueError(
                    f"Vocabulary asset rule: {path.name} has SHA256 {actual}, bytes={size}; download the cache matching the source contract."
                )


def _load_tables(
    connection,
    schema: str,
    directory: Path,
    entry: dict,
    *,
    destination: str | None = None,
) -> None:
    """Load within the caller's transaction, retaining primary keys and ANALYZE."""
    target = destination or schema
    if schema not in SCHEMAS or target not in (*SCHEMAS, "pg_temp"):
        raise ValueError(
            f"Vocabulary destination rule: found {target!r}; use a catalog schema or session-local probe tables."
        )
    connection.execute(
        f"TRUNCATE {target}.corpus_lexeme, {target}.corpus_surface_lexeme"
    )
    connection.execute(f"DROP INDEX IF EXISTS {target}.corpus_surface_lexeme_trgm_idx")
    for table in TABLES:
        with (
            connection.cursor().copy(
                f"COPY {target}.{table} (lexeme, ndoc, nentry) FROM STDIN WITH (FORMAT CSV)"
            ) as copy,
            gzip.open(directory / f"{schema}.{table}.csv.gz", "rb") as stream,
        ):
            while chunk := stream.read(1024 * 1024):
                copy.write(chunk)
        count = connection.execute(f"SELECT count(*) FROM {target}.{table}").fetchone()[
            0
        ]
        if count != entry["tables"][table]["rows"]:
            raise ValueError(
                f"Vocabulary row rule: {schema}.{table} has {count} rows; regenerate the complete cache."
            )
        connection.execute(f"ANALYZE {target}.{table}")
    connection.execute(
        f"CREATE INDEX corpus_surface_lexeme_trgm_idx ON {target}.corpus_surface_lexeme USING gin (lexeme gin_trgm_ops)"
    )


def restore(
    connection,
    schema: str,
    directory: Path,
    contract: dict,
    *,
    destination: str | None = None,
) -> dict:
    """Verify cache bindings before replacing any rows, with rollback on failure."""
    verify_files(directory, contract, schema=schema)
    if schema not in SCHEMAS:
        raise ValueError(
            f"Vocabulary schema rule: found {schema!r}; use one of {SCHEMAS}."
        )
    started = time.monotonic()
    with connection.transaction():
        connection.execute("SET LOCAL search_path = pg_catalog, public")
        actual_environment = environment_identity(connection)
        if actual_environment != contract["environment"]:
            raise ValueError(
                f"Vocabulary environment rule: found {actual_environment}; regenerate the cache on this PostgreSQL version, or unset MOSAIC_VOCABULARY_CACHE_DIR to rebuild."
            )
        # Hold the projection stable from fingerprint through publication. A
        # view lock also locks its underlying relations, including source rows.
        connection.execute(f"LOCK TABLE {schema}.product_document IN SHARE MODE")
        actual = fingerprint(connection, schema)
        entry = contract["schemas"][schema]
        if actual != entry["input"]:
            raise ValueError(
                f"Vocabulary input rule: {schema} has {actual}; regenerate the cache for this projection, or unset MOSAIC_VOCABULARY_CACHE_DIR to rebuild."
            )
        _load_tables(connection, schema, directory, entry, destination=destination)
    return {
        "phase": "corpus_vocabulary",
        "schema": schema,
        "mode": "cache",
        "seconds": round(time.monotonic() - started, 2),
    }


def refresh(connection, schema: str) -> dict:
    """Use the explicitly requested cache, otherwise run the ordinary rebuild."""
    if schema not in SCHEMAS:
        raise ValueError(
            f"Vocabulary schema rule: found {schema!r}; use one of {SCHEMAS}."
        )
    directory = os.environ.get("MOSAIC_VOCABULARY_CACHE_DIR")
    if directory:
        report = restore(
            connection, schema, Path(directory), json.loads(CONTRACT.read_text())
        )
    else:
        started = time.monotonic()
        connection.execute(f"CALL {schema}.refresh_corpus_lexeme()")
        report = {
            "phase": "corpus_vocabulary",
            "schema": schema,
            "mode": "rebuild",
            "seconds": round(time.monotonic() - started, 2),
        }
    print(json.dumps(report), flush=True)
    return report


def export(connection, directory: Path, *, schema: str | None = None) -> dict:
    """Recompute with production SQL and export exact, independently compared rows."""
    if schema is not None and schema not in SCHEMAS:
        raise ValueError(
            f"Vocabulary schema rule: found {schema!r}; use one of {SCHEMAS}."
        )
    directory.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": 1,
        "procedure_sha256": hashlib.sha256(procedure_sql().encode()).hexdigest(),
        "environment": environment_identity(connection),
        "schemas": {},
    }
    with connection.transaction():
        connection.execute("SET LOCAL search_path = pg_catalog, public")
        for table in TABLES:
            connection.execute(
                f"CREATE TEMP TABLE {table} (lexeme text PRIMARY KEY, ndoc bigint NOT NULL, nentry bigint NOT NULL) ON COMMIT DROP"
            )
        connection.execute(procedure_sql().replace("mosaic_search.", "pg_temp."))
        selected_schemas = (schema,) if schema else SCHEMAS
        for selected_schema in selected_schemas:
            started = time.monotonic()
            connection.execute(
                f"LOCK TABLE {selected_schema}.product_document IN SHARE MODE"
            )
            entry = {"input": fingerprint(connection, selected_schema), "tables": {}}
            connection.execute(
                f"CREATE OR REPLACE TEMP VIEW product_document AS SELECT {INPUT_COLUMNS} FROM {selected_schema}.product_document"
            )
            connection.execute("CALL pg_temp.refresh_corpus_lexeme()")
            for table in TABLES:
                differences = connection.execute(
                    f"SELECT count(*) FROM ((TABLE pg_temp.{table} EXCEPT ALL TABLE {selected_schema}.{table}) UNION ALL (TABLE {selected_schema}.{table} EXCEPT ALL TABLE pg_temp.{table})) d"
                ).fetchone()[0]
                if differences:
                    raise ValueError(
                        f"Vocabulary export rule: {selected_schema}.{table} differs from production recomputation by {differences} rows; rebuild the source vocabulary before exporting."
                    )
                path = directory / f"{selected_schema}.{table}.csv.gz"
                with (
                    connection.cursor().copy(
                        f'COPY (SELECT lexeme, ndoc, nentry FROM pg_temp.{table} ORDER BY lexeme COLLATE "C") TO STDOUT WITH (FORMAT CSV)'
                    ) as copy,
                    gzip.open(path, "wb", compresslevel=1) as stream,
                ):
                    for chunk in copy:
                        stream.write(chunk)
                entry["tables"][table] = {
                    "rows": connection.execute(
                        f"SELECT count(*) FROM pg_temp.{table}"
                    ).fetchone()[0],
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            contract["schemas"][selected_schema] = entry
            print(
                json.dumps(
                    {
                        "phase": "vocabulary_cache_export",
                        "schema": selected_schema,
                        "seconds": round(time.monotonic() - started, 2),
                        "row_differences": 0,
                    }
                ),
                flush=True,
            )
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "export", "refresh"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--schema", choices=SCHEMAS)
    args = parser.parse_args()
    if args.action in {"verify", "export"} and not args.directory:
        parser.error(f"{args.action} requires --directory")
    if args.action == "verify":
        verify_files(
            args.directory, json.loads(args.contract.read_text()), schema=args.schema
        )
        print("Vocabulary cache: every file and production SQL hash verified")
        return
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    with psycopg.connect(
        dsn, application_name="mosaic-corpus-vocabulary"
    ) as connection:
        connection.execute("SELECT aurora_version()")
        connection.execute("SET statement_timeout = '30min'")
        connection.execute("SET lock_timeout = '5s'")
        if args.action == "export":
            result = export(connection, args.directory, schema=args.schema)
            args.contract.write_text(json.dumps(result, indent=2) + "\n")
        else:
            if not args.schema:
                parser.error("refresh requires --schema")
            refresh(connection, args.schema)


if __name__ == "__main__":
    main()
