#!/usr/bin/env python3
"""Export Pydantic contracts as standalone JSON Schema files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models" / "python"))

from mosaic_models import (  # noqa: E402
    AgentToolEvent,
    CompareProductsRequest,
    EvidenceSearchRequest,
    MediaAsset,
    MerchandisingAssignment,
    ProductEvidenceIngest,
    ProductIngest,
    ProductMediaAssignment,
    ProductOfferIngest,
    SearchRequest,
    SearchResponse,
)

MODELS = {
    "product-ingest": ProductIngest,
    "product-offer-ingest": ProductOfferIngest,
    "media-asset": MediaAsset,
    "product-media-assignment": ProductMediaAssignment,
    "merchandising-assignment": MerchandisingAssignment,
    "product-evidence-ingest": ProductEvidenceIngest,
    "search-request": SearchRequest,
    "search-response": SearchResponse,
    "compare-products-request": CompareProductsRequest,
    "evidence-search-request": EvidenceSearchRequest,
    "agent-tool-event": AgentToolEvent,
}


def main() -> None:
    output = ROOT / "models" / "json-schema"
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS.items():
        path = output / f"{filename}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
