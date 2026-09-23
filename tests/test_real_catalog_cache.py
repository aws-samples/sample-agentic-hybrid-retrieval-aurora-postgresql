"""Release assets must fail closed before database mutation."""

import io
import tarfile

import pytest

from scripts import real_catalog_cache
from scripts.real_catalog_cache import digest, unpack, verify_archive


def bundle(tmp_path, extra=None):
    path = tmp_path / "cache.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name in ["selection.json", "catalog.jsonl.gz", *(extra or [])]:
            info = tarfile.TarInfo(name)
            info.size = 2
            archive.addfile(info, io.BytesIO(b"{}"))
    return path, {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "embedding_batches": 0,
        "review_samples": {},
    }


def test_verified_regular_members_extract(tmp_path):
    archive, contract = bundle(tmp_path)
    unpack(archive, tmp_path / "out", contract)
    assert (tmp_path / "out" / "selection.json").read_bytes() == b"{}"


def test_changed_archive_is_rejected_before_extracting(tmp_path):
    archive, contract = bundle(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash rule"):
        verify_archive(archive, contract)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "name",
    ["../escape", "/tmp/escape", ".env", "embeddings/../escape.npz", "selection.json"],
)
def test_valid_hash_does_not_authorize_unsafe_or_duplicate_members(tmp_path, name):
    archive, contract = bundle(tmp_path, [name])
    with pytest.raises(ValueError, match="member rule"):
        unpack(archive, tmp_path / "out", contract)
    assert not (tmp_path / "out").exists()


def test_missing_batch_is_not_a_complete_archive(tmp_path):
    archive, contract = bundle(tmp_path)
    contract["embedding_batches"] = 1
    with pytest.raises(ValueError, match="members rule"):
        unpack(archive, tmp_path / "out", contract)


def test_bootstrap_requires_real_cache_before_any_catalog_load():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "deploy/mosaic-bootstrap.sh").read_text()

    def verify(text):
        assert text.index("scripts/real_catalog_cache.py join") < text.index(
            "\n  make db-bootstrap-base\n"
        )
        assert text.index("scripts/real_catalog_cache.py restore") < text.index(
            "MISSION_GATE_REQUIRE_DB=1"
        )
        assert "printf '\\nMOSAIC_CATALOG_DATASET=%s\\n'" in text.replace("\\\\", "\\")

    verify(script)
    with pytest.raises((AssertionError, ValueError)):
        verify(
            script.replace(
                "scripts/real_catalog_cache.py restore", "echo missing-catalog-restore"
            )
        )


def test_eval_refuses_a_mixed_catalog_before_paid_scoring(monkeypatch):
    from scripts.run_eval import require_single_served_catalog

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    require_single_served_catalog([{"dataset_id": "reviews-2023-500k-v1"}])
    with pytest.raises(ValueError, match="one catalog"):
        require_single_served_catalog(
            [{"dataset_id": "reviews-2023-500k-v1"}, {"dataset_id": "synthetic-legacy"}]
        )


def test_eval_validation_checks_each_catalog_in_its_own_schema():
    from unittest.mock import MagicMock

    from scripts.run_eval import validate_query_contract

    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = []
    validate_query_contract(
        connection,
        [
            {"query_id": "old", "target_product_id": 1},
            {
                "query_id": "new",
                "target_product_id": 1000001,
                "dataset_id": "reviews-2023-500k-v1",
            },
        ],
    )
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert "mosaic_search.product_document" in statements[0]
    assert "mosaic_live_search.product_document" in statements[1]


def _split_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(real_catalog_cache, "PART_BYTES", 10)
    archive = tmp_path / "real-catalog.tar.gz"
    archive.write_bytes(bytes(range(25)))
    contract = {
        "bytes": 25,
        "sha256": real_catalog_cache.digest(archive),
    }
    contract["parts"] = real_catalog_cache.split_archive(archive, tmp_path / "parts")
    return archive, contract


def test_split_parts_rejoin_to_the_pinned_archive(tmp_path, monkeypatch):
    archive, contract = _split_fixture(tmp_path, monkeypatch)
    rebuilt = tmp_path / "rebuilt.tar.gz"

    assert [part["bytes"] for part in contract["parts"]] == [10, 10, 5]
    real_catalog_cache.join_parts(tmp_path / "parts", rebuilt, contract)

    assert rebuilt.read_bytes() == archive.read_bytes()
    assert not any((tmp_path / "parts").iterdir())


def test_join_refuses_a_changed_or_missing_part(tmp_path, monkeypatch):
    _, contract = _split_fixture(tmp_path, monkeypatch)
    parts = tmp_path / "parts"
    (parts / contract["parts"][1]["name"]).write_bytes(b"0123456789")

    with pytest.raises(ValueError, match="differs from the contract"):
        real_catalog_cache.join_parts(parts, tmp_path / "rebuilt", contract)

    (parts / contract["parts"][2]["name"]).unlink()
    contract["parts"] = contract["parts"][2:]
    with pytest.raises(ValueError, match="is missing"):
        real_catalog_cache.join_parts(parts, tmp_path / "rebuilt", contract)
