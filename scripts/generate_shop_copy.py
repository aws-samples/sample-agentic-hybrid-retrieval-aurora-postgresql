#!/usr/bin/env python3
"""Draft factual merchandising copy from a reviewed product snapshot.

The output is an authoring artifact. Promotion must refresh the canonical source,
Aurora projection, embeddings, evidence, and portable cache together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.bedrock import get_bedrock_client
from service.config import get_settings

COPY_PROMPT = """You are the catalog editor for Mosaic, a premium fictional
shopping site. Alex is furnishing a modern home office. These are synthetic
products; names stay fictional and unchanged, but specifications must be
plausible for actual products of this category.

Rewrite every supplied product's short_description and long_description.
Return JSON only: an array with product_id, short_description,
long_description, attributes (the complete final object), and editorial_notes.

Short description: one useful sentence, at most 120 characters. Convey two or
three concrete differentiators. No model/brand repetition, generic praise,
'premium', 'perfect', 'exceptional', 'designed for modern life', medical promises,
or unsupported performance claims. Different specs must produce different copy.
Long description: 45-85 words in natural, polished prose. Explain the intended
use, decisive specifications and one honest limitation or trade-off. It should
help choose between neighboring products, not just paraphrase the short line.

Use the supplied specifications. Retain sound attributes exactly. Some records
have a clearly WRONG CATEGORY SCHEMA (for example clothing attributes on a desk
organizer, or desktop-monitor refresh rates on a monitor arm). Only in that
case, replace those erroneous attributes with a coherent, realistic synthetic
specification for the named product category and explain every correction in
editorial_notes. Do not arbitrarily upgrade a weak product. Different options
should suit different needs. Never change any attributes when locked is true.
Do not add certifications, platform approvals, measured lab results, warranty,
shipping, compatibility guarantees or prices. Do not invent features merely to
make the story sound better. Keep these distinctions explicit:
- ANC reduces noise for the wearer; a microphone flag does NOT prove outgoing
  voice noise suppression. Multipoint is a connection feature, not call quality.
- recommended_hours is a catalog use recommendation, not a health guarantee.
  Do not sell a 4-hour chair as ideal for 12-hour workdays.
- Fixed lumbar/armrests/seat depth are fixed. Never call them adjustable.
- USB-C charging watts do not prove display transport or docking bandwidth.
- Color gamut percentages without a named gamut do not prove color accuracy.
- Unknown features are unknown, not false; a numeric zero or false IS meaningful.
- True wireless battery runtime must distinguish earbuds from case totals if
  that information exists; otherwise do not invent a per-charge figure.

Never mention authoring instructions, locked fields or data schemas in shopper copy. Never compare to an unnamed lineup or another model. Do not infer heat, physical size, comfort, battery test conditions, Ethernet speed, video support, or the absence of ports from unrelated fields. State only supplied facts and direct practical implications. If a feature is unknown, say so only when it matters to choosing the product. Do not copy the old descriptions' unsupported claims. The product title and
category define what it is; the valid attributes define what it does.
"""


def validate_batch(source: list[dict[str, Any]], draft: Any) -> list[dict[str, Any]]:
    """Reject identity drift, missing records, and changes to locked lab specs."""
    if not isinstance(draft, list):
        raise TypeError("Shop copy rule: expected an array; regenerate this batch.")
    expected = {row["product_id"]: row for row in source}
    found = [row.get("product_id") for row in draft if isinstance(row, dict)]
    if (
        len(found) != len(draft)
        or len(set(found)) != len(found)
        or set(found) != set(expected)
    ):
        raise ValueError(
            f"Shop copy identity rule: found {found}, expected {sorted(expected)}; "
            "regenerate the complete batch without adding or dropping products."
        )
    for row in draft:
        pid = row["product_id"]
        short = row.get("short_description")
        long = row.get("long_description")
        if not isinstance(short, str) or not 20 <= len(short) <= 120:
            raise ValueError(
                f"Shop copy length rule: product {pid} has short description {short!r}; "
                "write one factual sentence of 20-120 characters."
            )
        if not isinstance(long, str) or not 35 <= len(long.split()) <= 100:
            raise ValueError(
                f"Shop copy detail rule: product {pid} has {long!r}; "
                "write a factual 35-100 word description."
            )
        if not isinstance(row.get("attributes"), dict) or not row["attributes"]:
            raise ValueError(
                f"Shop copy specification rule: product {pid} has {row.get('attributes')!r}; "
                "include the complete specification object."
            )
        if (
            expected[pid].get("locked")
            and row["attributes"] != expected[pid]["attributes"]
        ):
            raise ValueError(
                f"Shop copy lab rule: product {pid} changed locked specifications; "
                "restore the input attributes exactly."
            )
    return draft


def generate_batch(source: list[dict[str, Any]], model_id: str) -> list[dict[str, Any]]:
    """Generate a reviewable batch, retrying only explicit validation feedback."""
    client = get_bedrock_client("bedrock-runtime")
    messages = [{"role": "user", "content": [{"text": json.dumps(source)}]}]
    for attempt in range(4):
        response = client.converse(
            modelId=model_id,
            system=[{"text": COPY_PROMPT}],
            messages=messages,
            inferenceConfig={"maxTokens": 10000},
        )
        raw = "".join(
            block.get("text", "") for block in response["output"]["message"]["content"]
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            return validate_batch(source, json.loads(raw))
        except (ValueError, TypeError) as error:
            if attempt == 3:
                raise ValueError(
                    f"Shop copy JSON rule: stop={response.get('stopReason')!r}, opening={raw[:160]!r}; regenerate this batch. {error}"
                ) from error
            messages.extend(
                [
                    response["output"]["message"],
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": str(error)
                                + " Return the corrected complete JSON array."
                            }
                        ],
                    },
                ]
            )
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    model = args.model_id or get_settings().synthesis_model_id
    if not model:
        raise SystemExit(
            "Shop copy model rule: no synthesis model configured; set BEDROCK_SYNTHESIS_MODEL_ID."
        )
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    partials = output.parent / (output.stem + "-batches")
    partials.mkdir(exist_ok=True)
    batches = [source[offset : offset + 4] for offset in range(0, len(source), 4)]

    def write_batch(index: int) -> list[dict[str, Any]]:
        fingerprint = hashlib.sha256(
            json.dumps(batches[index], sort_keys=True).encode()
        ).hexdigest()[:12]
        path = partials / f"{index:03}-{fingerprint}.json"
        if path.exists():
            return validate_batch(batches[index], json.loads(path.read_text()))
        draft = generate_batch(batches[index], model)
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
        print(
            f"Drafted {len(draft)} products in batch {index + 1}/{len(batches)}",
            flush=True,
        )
        return draft

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        rows = [
            row
            for batch in executor.map(write_batch, range(len(batches)))
            for row in batch
        ]
    validate_batch(source, rows)
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} review drafts to {output}")


if __name__ == "__main__":
    main()
