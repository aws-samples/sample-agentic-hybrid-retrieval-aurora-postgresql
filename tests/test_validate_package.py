"""Delivery checks must reject damaged real-catalog contracts."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.checks.validate_package import validate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path):
    for name in (
        "db/config/real-catalog-cache.json",
        "db/config/corpus-vocabulary-cache.json",
        "data/real-shop-collection.json",
        "data/evals/canonical_queries.jsonl",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_real_package_has_archive_shop_and_judged_query_witnesses(package):
    assert validate(package) == {
        "archive_parts": 3,
        "shop_products": 120,
        "canonical_queries": 10,
    }


@pytest.mark.parametrize(
    "field,value,rule",
    [
        ("bytes", 0, "Catalog archive size rule"),
        ("sha256", "unverified", "Catalog archive digest rule"),
        ("embedding_model_id", "wrong-model", "Catalog model rule"),
    ],
)
def test_catalog_contract_corruption_fails_then_byte_identical_restore_passes(
    package, field, value, rule
):
    path = package / "db/config/real-catalog-cache.json"
    original = path.read_bytes()
    contract = json.loads(original)
    contract[field] = value
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match=rule):
        validate(package)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert validate(package)["archive_parts"] == 3


def test_duplicate_archive_part_names_fail(package):
    path = package / "db/config/real-catalog-cache.json"
    contract = json.loads(path.read_text())
    contract["parts"][1]["name"] = contract["parts"][0]["name"]
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="Catalog part names rule"):
        validate(package)


def test_wrong_shop_dataset_fails(package):
    path = package / "data/real-shop-collection.json"
    collection = json.loads(path.read_text())
    collection["dataset_id"] = "retired-catalog"
    path.write_text(json.dumps(collection))
    with pytest.raises(ValueError, match="Shop dataset rule"):
        validate(package)


def test_description_changes_do_not_invalidate_contract(package):
    path = package / "data/real-shop-collection.json"
    collection = json.loads(path.read_text())
    collection["description"] = "Editorial wording independent of identity."
    path.write_text(json.dumps(collection))
    assert validate(package)["shop_products"] == 120
