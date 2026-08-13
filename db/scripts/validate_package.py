#!/usr/bin/env python3
"""Offline validation for the Mosaic data-model package."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION FAILED: {message}")


def validate_cohort() -> dict[str, object]:
    path = ROOT / "data" / "premium_cohort_120.json"
    cohort = json.loads(path.read_text(encoding="utf-8"))
    if len(cohort) != 120:
        fail(f"premium cohort has {len(cohort)} rows, expected 120")
    ids = [row["product_id"] for row in cohort]
    if len(ids) != len(set(ids)):
        fail("premium cohort product IDs are not unique")
    distribution = Counter(row["domain"] for row in cohort)
    expected = Counter({"consumer_electronics": 48, "running_fitness": 36, "home_office": 36})
    if distribution != expected:
        fail(f"premium distribution {distribution} != {expected}")
    flagships = [row for row in cohort if row["is_flagship"]]
    if len(flagships) != 6:
        fail(f"flagship count {len(flagships)} != 6")
    anchors = [row for row in cohort if row["is_retrieval_anchor"]]
    if len(anchors) != 30:
        fail(f"anchor count {len(anchors)} != 30")
    anchor_distribution = Counter(row["domain"] for row in anchors)
    if anchor_distribution != Counter({"consumer_electronics": 10, "running_fitness": 10, "home_office": 10}):
        fail(f"anchor distribution is {anchor_distribution}")
    pages = Counter(row["shop_page"] for row in cohort)
    if pages != Counter({page: 12 for page in range(1, 11)}):
        fail(f"Shop page distribution is {pages}")
    positions = [(row["shop_page"], row["shop_position"]) for row in cohort]
    if len(positions) != len(set(positions)):
        fail("duplicate Shop page/position assignment")
    for row in flagships:
        if not row["detail_asset_key"]:
            fail(f"flagship {row['product_id']} is missing detail_asset_key")
    return {
        "products": len(cohort),
        "distribution": dict(distribution),
        "flagships": len(flagships),
        "anchors": len(anchors),
        "pages": len(pages),
    }


def validate_json_schemas() -> int:
    count = 0
    for path in sorted((ROOT / "models" / "json-schema").glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        cls = validator_for(schema)
        cls.check_schema(schema)
        count += 1
    if count < 8:
        fail(f"only {count} JSON schemas found")
    return count


def validate_python_models() -> None:
    path = ROOT / "models" / "python" / "mosaic_models.py"
    spec = importlib.util.spec_from_file_location("mosaic_models", path)
    if not spec or not spec.loader:
        fail("could not load Pydantic models")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    request = module.SearchRequest(query="comfortable headphones for a long flight")
    if request.profile.rrf_k != 60:
        fail("SearchRequest defaults are inconsistent")


def validate_sql() -> dict[str, int]:
    sql_dir = ROOT / "sql"
    files = sorted(sql_dir.glob("*.sql"))
    required = {
        "00_extensions.sql", "01_schemas_and_types.sql", "03_catalog.sql",
        "05_evidence.sql", "06_retrieval_projection.sql", "07_indexes.sql",
        "08_indexes_concurrent.sql", "09_search_functions.sql", "10_agent_audit.sql",
        "11_evaluation.sql", "12_telemetry.sql", "13_benchmark.sql",
        "15_load_premium_cohort.sql", "17_load_normalized_catalog.sql",
        "18_load_evidence.sql", "install.sql",
        # Evaluation and benchmark schemas install separately so a session's
        # `\dt mosaic.*` shows only the tables the application reads.
        "install_labs.sql", "upgrade_snapshot.sql",
    }
    missing = required - {path.name for path in files}
    if missing:
        fail(f"missing SQL files: {sorted(missing)}")
    unresolved = []
    legacy_hits = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"\{\{[A-Z_][A-Z0-9_]*\}\}", text):
            unresolved.append(path.name)
        if re.search(rf"\b{'V' + 'erity'}\b", text, re.IGNORECASE):
            legacy_hits.append(path.name)
        # Match an actual include, not any mention: install.sql documents the
        # concurrent step in its echo output, and forbidding the words would
        # push that instruction out of the place it is most useful.
        if path.name == "install.sql" and re.search(
            r"^\s*\\i(?:r)?\s+08_indexes_concurrent\.sql", text, re.MULTILINE
        ):
            fail("install.sql must not invoke CREATE INDEX CONCURRENTLY")
    if unresolved:
        fail(f"unresolved SQL placeholders: {unresolved}")
    if legacy_hits:
        fail(f"stale legacy branding in SQL: {legacy_hits}")
    return {"sql_files": len(files)}


def validate_package_branding() -> None:
    allowed_binary_suffixes = {".zip", ".png", ".webp", ".jpg", ".jpeg"}
    stale = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() in allowed_binary_suffixes or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if re.search(rf"\b{'V' + 'erity'}\b", text, re.IGNORECASE):
            stale.append(str(path.relative_to(ROOT)))
    if stale:
        fail(f"stale legacy branding: {stale}")


def main() -> None:
    summary = {
        "cohort": validate_cohort(),
        "json_schemas": validate_json_schemas(),
        **validate_sql(),
    }
    validate_python_models()
    validate_package_branding()
    print(json.dumps({"status": "ok", **summary}, indent=2))


if __name__ == "__main__":
    main()
