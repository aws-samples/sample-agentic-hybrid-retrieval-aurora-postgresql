"""Check one sentence against the agent's answer-of-record rules, citing a product's listing.

    uv run python scripts/check_claim.py PRODUCT_ID "A SENTENCE THAT CITES [1]"

[1] is the product's current listing record, its specifications. The sentence goes through
`validate_cited_answer`, the checks `synthesize_cited_answer` applies to every draft the
agent writes: each [n] must name a supplied record, the product must be cited, and every
figure the sentence states must appear in the cited record in that unit. Nothing is
generated or saved, so the same sentence always gets the same verdict.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.catalog import get_evidence_record, get_product_summaries
from service.catalog_runtime import active_dataset
from service.db import connect
from service.models import EvidenceRecord
from service.synthesis import SynthesisOutputError, validate_cited_answer


def listing_record(product_id: int) -> EvidenceRecord:
    """The product's current listing (`product_spec`) record."""
    if active_dataset():
        from service.live_catalog import ensure_product_evidence

        ensure_product_evidence(product_id)
    with connect() as connection:
        row = connection.execute(
            """
            SELECT evidence_id
            FROM mosaic.product_evidence
            WHERE product_id = %s AND is_current AND evidence_type::text = 'product_spec'
            ORDER BY evidence_id
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"product {product_id} has no current listing record")
    return get_evidence_record(row["evidence_id"])


def check(product_id: int, sentence: str) -> tuple[bool, str]:
    """Return whether the answer checks accept the sentence, and why not when they refuse."""
    products = get_product_summaries([product_id])
    try:
        validate_cited_answer(sentence, products, [listing_record(product_id)])
    except SynthesisOutputError as error:
        return False, str(error)
    return True, "every citation names the listing and every stated figure is in it"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("product_id", type=int)
    parser.add_argument("sentence")
    args = parser.parse_args(argv)
    products = get_product_summaries([args.product_id])
    if not products:
        print(
            f"Claim check rule: product {args.product_id} is not in the catalog; fix: use "
            "a product ID from your run, such as 1551237 for the ViewSonic VG2756-4K",
            file=sys.stderr,
        )
        return 2
    record = listing_record(args.product_id)
    print(f"[1] {record.evidence_type}  {record.product_id}  {record.title}")
    print(f"Sentence: {args.sentence}")
    passed, detail = check(args.product_id, args.sentence)
    print(("PASS: " if passed else "BLOCKED: ") + detail)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
