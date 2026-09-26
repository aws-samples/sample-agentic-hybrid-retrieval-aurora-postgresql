"""A fresh workshop must never depend on generated product or evidence rows."""

import copy
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.run_eval import select_catalog_queries
from scripts.verify_real_bootstrap import verify

ROOT = Path(__file__).resolve().parents[1]


def test_schema_bootstrap_dry_run_never_loads_synthetic_data():
    result = subprocess.run(
        [
            "make",
            "--dry-run",
            "db-bootstrap-schema",
            "DATABASE_URL=aurora-contract-probe",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "make db-install " in result.stdout
    assert "make db-install-labs " in result.stdout
    for forbidden in (
        "db-load-mosaic",
        "db-prepare-mosaic",
        "db-load-evidence",
        "db-load-cohort",
        "db-seed-corpus-lexeme",
        "transform_legacy_catalog.py",
        "export_premium_cohort.py",
        "17_load_normalized_catalog.sql",
        "15_load_premium_cohort.sql",
        "18_load_evidence.sql",
        "corpus_vocabulary.py refresh",
        "08_indexes_concurrent.sql",
    ):
        assert forbidden not in result.stdout


def test_real_query_selection_excludes_legacy_and_rejects_an_empty_selection():
    real = {"dataset_id": "reviews-2023-v2", "query_id": "real"}
    queries = [{"query_id": "legacy"}, real, {"dataset_id": "synthetic-legacy"}]
    assert select_catalog_queries(queries, "reviews-2023-v2") == [real]
    with pytest.raises(ValueError, match="no queries"):
        select_catalog_queries(queries, "unknown")


def test_published_query_files_keep_real_and_synthetic_identities_separate():
    from scripts.eval_contract import load_evaluation_queries

    real = load_evaluation_queries(ROOT / "data/evals/canonical_queries.jsonl")
    legacy = load_evaluation_queries(
        ROOT / "data/evals/historical/canonical_queries.jsonl"
    )
    dataset = json.loads((ROOT / "db/config/real-catalog-cache.json").read_text())[
        "dataset_id"
    ]
    assert real and legacy
    assert {query.get("dataset_id") for query in real} == {dataset}
    assert {query.get("dataset_id", "synthetic-legacy") for query in legacy} == {
        "synthetic-legacy"
    }
    assert not {q["query_id"] for q in real} & {q["query_id"] for q in legacy}


@pytest.mark.parametrize(
    "path", ["substrate", "measured", "anchors", "neighborhood/1", "probe"]
)
def test_real_catalog_withholds_legacy_hnsw_before_any_database_access(
    monkeypatch, path
):
    from fastapi.testclient import TestClient

    from service import hnsw
    from service.main import app

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    monkeypatch.setattr(
        hnsw, "connect", lambda: pytest.fail("must not read the historical database")
    )
    client = TestClient(app)
    response = (
        client.post("/api/hnsw/probe", json={})
        if path == "probe"
        else client.get(f"/api/hnsw/{path}")
    )
    assert response.status_code == 409
    assert "Lab 1" in response.json()["detail"]


@pytest.mark.aurora
def test_real_only_acceptance_rejects_synthetic_brand_and_rolls_back_byte_identical():
    import psycopg
    from psycopg.rows import dict_row

    from service.config import get_settings

    contract = json.loads((ROOT / "db/config/real-catalog-cache.json").read_text())
    with psycopg.connect(
        get_settings().database_url, row_factory=dict_row
    ) as connection:
        if connection.execute(
            "SELECT count(*) AS n FROM mosaic.product WHERE source_system IS DISTINCT FROM %s",
            (contract["dataset_id"],),
        ).fetchone()["n"]:
            pytest.skip("Requires a fresh real-only Aurora restore")
        baseline = verify(connection, contract)
        brand = connection.execute(
            "SELECT * FROM mosaic.brand ORDER BY brand_id LIMIT 1"
        ).fetchone()
        connection.commit()
        with (
            pytest.raises(ValueError, match="Real-only bootstrap rule"),
            connection.transaction(),
        ):
            connection.execute(
                "UPDATE mosaic.brand SET is_synthetic=true WHERE brand_id=%s",
                (brand["brand_id"],),
            )
            verify(connection, contract)
        restored = connection.execute(
            "SELECT * FROM mosaic.brand WHERE brand_id=%s", (brand["brand_id"],)
        ).fetchone()
        assert restored == brand
        assert verify(connection, contract) == baseline


@pytest.mark.parametrize(
    "violation",
    [
        "foreign_products",
        "synthetic_brands",
        "legacy_documents",
        "legacy_lexemes",
        "legacy_surface_lexemes",
        "registered_products",
        "products",
        "embedded_products",
        "receipt",
        "index",
        "vocabulary",
    ],
)
def test_acceptance_rejects_each_violation_then_accepts_identical_restoration(
    violation,
):
    contract = json.loads((ROOT / "db/config/real-catalog-cache.json").read_text())
    counts = dict.fromkeys(
        (
            "foreign_products",
            "synthetic_brands",
            "legacy_documents",
            "legacy_lexemes",
            "legacy_surface_lexemes",
        ),
        0,
    )
    counts.update(
        dict.fromkeys(
            ("registered_products", "products", "embedded_products"),
            contract["products"],
        )
    )
    receipt = {key: contract[key] for key in ("dataset_id", "catalog_sha256")}

    def connection_for(measured, saved_receipt, indexes, ready):
        connection = MagicMock()
        results = [MagicMock() for _ in range(5)]
        results[1].fetchone.return_value = measured
        results[2].fetchone.return_value = saved_receipt
        results[3].fetchall.return_value = indexes
        results[4].fetchone.return_value = {"ready": ready}
        connection.execute.side_effect = results
        return connection

    before = json.dumps([counts, receipt], sort_keys=True)
    broken = copy.deepcopy(counts)
    if violation in broken:
        broken[violation] += 1
    with pytest.raises(ValueError, match="Real-only .*rule:"):
        verify(
            connection_for(
                broken,
                None if violation == "receipt" else receipt,
                [{"name": "real_search_vector_idx"}] if violation == "index" else [],
                violation != "vocabulary",
            ),
            contract,
        )
    assert json.dumps([counts, receipt], sort_keys=True) == before
    assert verify(connection_for(counts, receipt, [], True), contract) == counts


def test_real_only_scorecard_population_is_pending_without_breaking_lab_proof():
    from service.scorecard import retrieval_scorecard

    response = retrieval_scorecard()
    assert response.provenance.attributed is False
    assert response.retrieval_quality is None
    assert response.regression_anchors.anchors == []
