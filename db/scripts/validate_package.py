#!/usr/bin/env python3
"""Offline validation for the Mosaic data-model package."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION FAILED: {message}")


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
        "00_extensions.sql",
        "01_schemas_and_types.sql",
        "03_catalog.sql",
        "05_evidence.sql",
        "06_retrieval_projection.sql",
        "07_indexes.sql",
        "15_indexes_concurrent.sql",
        "08_search_channels.sql",
        "09_weighted_fusion.sql",
        "10_evidence_search.sql",
        "12_agent_audit.sql",
        "20_evaluation.sql",
        "13_telemetry.sql",
        "21_benchmark.sql",
        "install.sql",
        # Evaluation and benchmark schemas install separately so a session's
        # `\dt mosaic.*` shows only the tables the application reads.
        "install_measurement.sql",
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
        if (
            not path.is_file()
            or path.suffix.lower() in allowed_binary_suffixes
            or "__pycache__" in path.parts
        ):
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
        "json_schemas": validate_json_schemas(),
        **validate_sql(),
    }
    validate_python_models()
    validate_package_branding()
    print(json.dumps({"status": "ok", **summary}, indent=2))


if __name__ == "__main__":
    main()
