#!/usr/bin/env python3
"""Validate the real-catalog delivery contracts without downloading ignored assets."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog.corpus_vocabulary import verify_contract
from scripts.catalog.embedding_model import (
    COHERE_EMBED_V4_DIMENSIONS,
    COHERE_EMBED_V4_MODEL_ID,
)
from scripts.evals.eval_contract import load_evaluation_queries
from service.models import SearchFilters


def require(condition: bool, rule: str, value: object, fix: str) -> None:
    """Reject an invalid delivery contract with the offending value and repair."""
    if not condition:
        raise ValueError(f"{rule}: found {value!r}; fix: {fix}.")


def validate(root: Path = ROOT) -> dict[str, int]:
    """Check archive metadata, vocabulary SQL, Shop identities and labeled queries."""
    contract = json.loads((root / "db/config/real-catalog-cache.json").read_text())
    parts = contract.get("parts", [])
    require(
        bool(parts),
        "Catalog parts rule",
        parts,
        "split the verified real-catalog archive",
    )
    names = [part["name"] for part in parts]
    require(
        len(set(names)) == len(names)
        and all(
            re.fullmatch(r"real-catalog\.tar\.gz\.part-\d{3}", name) for name in names
        ),
        "Catalog part names rule",
        names,
        "use distinct numbered archive parts",
    )
    for part in parts:
        require(
            0 < part["bytes"] <= 1_000_000_000
            and bool(re.fullmatch(r"[0-9a-f]{64}", part["sha256"])),
            "Catalog part contract rule",
            part,
            "regenerate the archive part contract",
        )
    total = sum(part["bytes"] for part in parts)
    require(
        total == contract["bytes"],
        "Catalog archive size rule",
        total,
        "make the parts sum to the archive's pinned bytes",
    )
    require(
        bool(re.fullmatch(r"[0-9a-f]{64}", contract["sha256"])),
        "Catalog archive digest rule",
        contract["sha256"],
        "pin the verified archive SHA-256",
    )
    require(
        (contract["embedding_model_id"], contract["dimensions"])
        == (COHERE_EMBED_V4_MODEL_ID, COHERE_EMBED_V4_DIMENSIONS),
        "Catalog model rule",
        (contract["embedding_model_id"], contract["dimensions"]),
        "restore the workshop's Cohere Embed v4 model space",
    )
    vocabulary = json.loads(
        (root / "db/config/corpus-vocabulary-cache.json").read_text()
    )
    verify_contract(vocabulary)
    collection = json.loads((root / "data/real-shop-collection.json").read_text())
    require(
        collection["dataset_id"] == contract["dataset_id"],
        "Shop dataset rule",
        collection["dataset_id"],
        "regenerate the Shop selection from the active catalog",
    )
    identities = [
        asin for group in collection["groups"] for asin in group["parent_asins"]
    ]
    require(
        bool(identities) and len(identities) == len(set(identities)),
        "Shop identity rule",
        identities,
        "select distinct source listing IDs",
    )
    queries = load_evaluation_queries(root / "data/evals/canonical_queries.jsonl")
    require(
        bool(queries),
        "Evaluation corpus rule",
        queries,
        "retain the real-catalog judged queries",
    )
    for query in queries:
        require(
            query.get("dataset_id") == contract["dataset_id"],
            "Evaluation dataset rule",
            query.get("dataset_id"),
            "use judgments for the selected real catalog",
        )
        SearchFilters.model_validate(query.get("filters") or {})
    return {
        "archive_parts": len(parts),
        "shop_products": len(identities),
        "canonical_queries": len(queries),
    }


if __name__ == "__main__":
    print(json.dumps(validate(), sort_keys=True))
