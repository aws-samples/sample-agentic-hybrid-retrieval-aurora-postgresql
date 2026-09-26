"""Vocabulary acceleration must reject stale inputs before replacing any rows."""

import copy
import gzip
import hashlib
import json
from unittest.mock import MagicMock

import pytest

from scripts import corpus_vocabulary as vocabulary


def test_published_contract_agrees_with_production_sql_without_ignored_assets():
    contract = json.loads(vocabulary.CONTRACT.read_text())
    vocabulary.verify_contract(contract)
    assert set(contract["schemas"]) == {"mosaic_live_search"}
    assert all(entry["input"]["products"] > 0 for entry in contract["schemas"].values())


@pytest.fixture
def cache(tmp_path):
    contract = {
        "schema_version": 1,
        "procedure_sha256": hashlib.sha256(
            vocabulary.procedure_sql().encode()
        ).hexdigest(),
        "environment": {
            "server_version_num": "180003",
            "encoding": "UTF8",
            "simple_dictionaries": [],
        },
        "schemas": {},
    }
    for schema in vocabulary.SCHEMAS:
        entry = {
            "input": {"products": 2, "sha256": "verified-projection"},
            "tables": {},
        }
        for table in vocabulary.TABLES:
            path = tmp_path / f"{schema}.{table}.csv.gz"
            path.write_bytes(gzip.compress(b"chair,2,4\nheadphones,1,1\n"))
            entry["tables"][table] = {
                "rows": 2,
                "sha256": vocabulary.digest(path),
                "bytes": path.stat().st_size,
            }
        contract["schemas"][schema] = entry
    return tmp_path, contract


def test_files_are_verified_and_unrelated_files_do_not_invalidate(cache):
    directory, contract = cache
    vocabulary.verify_files(directory, contract)
    (directory / "operator-notes.txt").write_text("irrelevant to vocabulary")
    vocabulary.verify_files(directory, contract)
    assert sum(len(entry["tables"]) for entry in contract["schemas"].values()) == 4


def test_real_only_cache_needs_no_historical_files_but_rejects_changed_real_bytes(
    cache,
):
    directory, contract = cache
    for path in directory.glob("mosaic_search.*"):
        path.unlink()
    vocabulary.verify_files(directory, contract, schema="mosaic_live_search")
    path = directory / "mosaic_live_search.corpus_lexeme.csv.gz"
    before = path.read_bytes()
    path.write_bytes(before + b"changed")
    with pytest.raises(ValueError, match="Vocabulary asset rule"):
        vocabulary.verify_files(directory, contract, schema="mosaic_live_search")
    path.write_bytes(before)
    assert path.read_bytes() == before
    vocabulary.verify_files(directory, contract, schema="mosaic_live_search")


@pytest.mark.parametrize(
    "violation", ["changed", "missing", "size", "sql", "table", "schema", "version"]
)
def test_each_asset_gate_rejects_its_violation_then_accepts_byte_identical_restore(
    cache, violation
):
    directory, original = cache
    contract = copy.deepcopy(original)
    path = directory / "mosaic_live_search.corpus_surface_lexeme.csv.gz"
    before = path.read_bytes()
    if violation == "changed":
        path.write_bytes(before + b"changed")
    elif violation == "missing":
        path.unlink()
    elif violation == "size":
        contract["schemas"]["mosaic_live_search"]["tables"]["corpus_surface_lexeme"][
            "bytes"
        ] += 1
    elif violation == "sql":
        contract["procedure_sha256"] = "stale-procedure"
    elif violation == "table":
        contract["schemas"]["unsupported_schema"] = contract["schemas"].pop(
            "mosaic_live_search"
        )["tables"]["corpus_surface_lexeme"]
    elif violation == "schema":
        contract["schemas"]["unsupported_schema"] = contract["schemas"].pop(
            "mosaic_live_search"
        )
    else:
        contract["schema_version"] = 0
    connection = MagicMock()
    with pytest.raises(ValueError, match="Vocabulary .* rule:"):
        vocabulary.restore(connection, "mosaic_live_search", directory, contract)
    connection.execute.assert_not_called()
    path.write_bytes(before)
    assert path.read_bytes() == before
    vocabulary.verify_files(directory, original)


@pytest.mark.parametrize("violation", ["environment", "input"])
def test_binding_mismatch_never_reaches_copy_or_truncate(cache, monkeypatch, violation):
    directory, contract = cache
    connection = MagicMock()
    environment = copy.deepcopy(contract["environment"])
    fingerprint = copy.deepcopy(contract["schemas"]["mosaic_search"]["input"])
    if violation == "environment":
        environment["server_version_num"] = "180004"
    else:
        fingerprint["sha256"] = "changed-projection"
    monkeypatch.setattr(vocabulary, "environment_identity", lambda _: environment)
    monkeypatch.setattr(vocabulary, "fingerprint", lambda *_: fingerprint)
    with pytest.raises(ValueError, match=f"Vocabulary {violation} rule:"):
        vocabulary.restore(connection, "mosaic_search", directory, contract)
    assert not any(
        "TRUNCATE" in call.args[0] for call in connection.execute.call_args_list
    )
    connection.cursor.assert_not_called()


def test_success_loads_both_tables_and_rebuilds_the_index(cache, monkeypatch):
    directory, contract = cache
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (2,)
    monkeypatch.setattr(
        vocabulary, "environment_identity", lambda _: contract["environment"]
    )
    monkeypatch.setattr(
        vocabulary,
        "fingerprint",
        lambda *_: contract["schemas"]["mosaic_search"]["input"],
    )
    report = vocabulary.restore(connection, "mosaic_search", directory, contract)
    assert report["mode"] == "cache"
    assert connection.cursor.return_value.copy.call_count == 2
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert sum(statement.startswith("ANALYZE") for statement in statements) == 2
    assert statements[-1].startswith("CREATE INDEX corpus_surface_lexeme_trgm_idx")
    connection.transaction.assert_called_once()


def test_operator_rebuild_executes_the_production_procedure(monkeypatch):
    monkeypatch.delenv("MOSAIC_VOCABULARY_CACHE_DIR", raising=False)
    connection = MagicMock()
    report = vocabulary.refresh(connection, "mosaic_live_search")
    connection.execute.assert_called_once_with(
        "CALL mosaic_live_search.refresh_corpus_lexeme()"
    )
    assert report["mode"] == "rebuild"


def test_bootstrap_verifies_vocabulary_before_loading_either_catalog():
    script = (vocabulary.ROOT / "deploy/mosaic-bootstrap.sh").read_text()
    assert script.index("scripts/corpus_vocabulary.py verify") < script.index(
        "\n  make db-bootstrap-schema\n"
    )
    assert (
        "export MOSAIC_VOCABULARY_CACHE_DIR=build/real-catalog-cache/vocabulary"
        in script
    )


@pytest.mark.aurora
def test_actual_restore_is_atomic_and_input_binding_ignores_unread_columns(
    tmp_path, monkeypatch
):
    """Exercise COPY, index DDL, failure rollback and the actual fingerprint on Aurora."""
    import psycopg

    from service.config import get_settings

    monkeypatch.setattr(vocabulary, "SCHEMAS", ("pg_temp",))
    with psycopg.connect(get_settings().database_url) as connection:
        connection.execute("SELECT aurora_version()")
        connection.execute(
            "CREATE TEMP TABLE product_document (product_id bigint, search_document tsvector, title_text text, identity_text text, feature_text text, body_text text, trigram_text text, unrelated text)"
        )
        connection.execute(
            "INSERT INTO product_document VALUES (1, to_tsvector('english', 'chair chair'), 'chair chair', '', '', '', '', 'original')"
        )
        for table in vocabulary.TABLES:
            connection.execute(
                f"CREATE TEMP TABLE {table} (lexeme text PRIMARY KEY, ndoc bigint NOT NULL, nentry bigint NOT NULL)"
            )
        connection.execute(
            vocabulary.procedure_sql().replace("mosaic_search.", "pg_temp.")
        )
        connection.execute("CALL pg_temp.refresh_corpus_lexeme()")
        contract = {
            "schema_version": 1,
            "procedure_sha256": hashlib.sha256(
                vocabulary.procedure_sql().encode()
            ).hexdigest(),
            "environment": vocabulary.environment_identity(connection),
            "schemas": {
                "pg_temp": {
                    "input": vocabulary.fingerprint(connection, "pg_temp"),
                    "tables": {},
                }
            },
        }
        entry = contract["schemas"]["pg_temp"]
        for table in vocabulary.TABLES:
            rows = connection.execute(f"TABLE pg_temp.{table}").fetchall()
            assert rows == [("chair", 1, 2)]
            path = tmp_path / f"pg_temp.{table}.csv.gz"
            path.write_bytes(gzip.compress(b"chair,1,2\n"))
            entry["tables"][table] = {
                "rows": 1,
                "sha256": vocabulary.digest(path),
                "bytes": path.stat().st_size,
            }
        connection.execute("UPDATE product_document SET unrelated='changed'")
        assert (
            vocabulary.restore(connection, "pg_temp", tmp_path, contract)["mode"]
            == "cache"
        )
        assert connection.execute(
            "SELECT indisvalid FROM pg_index WHERE indexrelid='pg_temp.corpus_surface_lexeme_trgm_idx'::regclass"
        ).fetchone() == (True,)
        connection.execute("UPDATE product_document SET title_text='different input'")
        with pytest.raises(ValueError, match="Vocabulary input rule"):
            vocabulary.restore(connection, "pg_temp", tmp_path, contract)
        connection.execute("UPDATE product_document SET title_text='chair chair'")
        connection.execute("INSERT INTO corpus_lexeme VALUES ('sentinel', 9, 9)")
        bad = copy.deepcopy(contract)
        bad["schemas"]["pg_temp"]["tables"]["corpus_surface_lexeme"]["rows"] = 99
        with pytest.raises(ValueError, match="Vocabulary row rule"):
            vocabulary.restore(connection, "pg_temp", tmp_path, bad)
        assert connection.execute(
            "SELECT ndoc FROM corpus_lexeme WHERE lexeme='sentinel'"
        ).fetchone() == (9,)
        assert connection.execute(
            "SELECT indisvalid FROM pg_index WHERE indexrelid='pg_temp.corpus_surface_lexeme_trgm_idx'::regclass"
        ).fetchone() == (True,)
        vocabulary.restore(connection, "pg_temp", tmp_path, contract)
        assert connection.execute("TABLE corpus_lexeme").fetchall() == [("chair", 1, 2)]
