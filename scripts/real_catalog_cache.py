#!/usr/bin/env python3
"""Package and restore the verified real catalog without generating embeddings.

The release contract pins the archive bytes in source control. Only selected
records, their saved vectors and source-verified review samples enter the bundle;
operator logs, credentials and intermediate experiments are never included.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.embed_real_catalog import (
    batch_identity,
    iter_batches,
    load_batch,
    verified_selection,
)
from scripts.fetch_catalog_reviews import source_identity, verify_review
from scripts.prepare_real_catalog import canonical, sha256

CONTRACT = ROOT / "db/config/real-catalog-cache.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_selection(directory: Path) -> tuple[dict, list[Path]]:
    """Verify every source/input/vector binding before publishing or importing."""
    selection = verified_selection(directory)
    paths = [directory / "selection.json", directory / "catalog.jsonl.gz"]
    count = 0
    for rows in iter_batches(directory):
        identity = batch_identity(rows)
        path = directory / "embeddings" / (sha256(canonical(identity)) + ".npz")
        load_batch(path, identity)
        paths.append(path)
        count += len(rows)
    if count != selection["products"]:
        raise ValueError(
            f"Real cache count rule: found {count}, expected {selection['products']}; restore the complete selection."
        )
    return selection, paths


def export(directory: Path, reviews: list[Path], output: Path, dataset: str) -> dict:
    """Write a bounded allowlist, then bind its bytes to the source contract."""
    from scripts.stage_catalog_evidence import verified_samples

    selection, paths = verify_selection(directory)
    review_counts = {}
    for path in reviews:
        _, rows = verified_samples(path)
        review_counts[path.name] = len(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    with tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
        for path in paths:
            archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
        for path in reviews:
            archive.add(path, arcname="reviews/" + path.name, recursive=False)
    temporary.replace(output)
    return {
        "schema_version": 1,
        "dataset_id": dataset,
        "archive": output.name,
        "sha256": digest(output),
        "bytes": output.stat().st_size,
        "catalog_sha256": selection["catalog_sha256"],
        "products": selection["products"],
        "embedding_model_id": "us.cohere.embed-v4:0",
        "dimensions": 1024,
        "embedding_batches": len(paths) - 2,
        "review_samples": review_counts,
        "distribution_status": "Prepared locally; public redistribution clearance remains an event-owner release requirement.",
    }


def verify_archive(path: Path, contract: dict) -> None:
    """Refuse a stale or changed asset before extracting it or opening Aurora."""
    actual = digest(path)
    if path.stat().st_size != contract["bytes"] or actual != contract["sha256"]:
        raise ValueError(
            f"Real cache hash rule: found {actual}, expected {contract['sha256']}; publish the archive for this exact source commit."
        )


def unpack(path: Path, output: Path, contract: dict) -> None:
    """Permit regular allowlisted files only, even for a correctly hashed archive."""
    verify_archive(path, contract)
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            name = Path(member.name)
            allowed = member.name in {"selection.json", "catalog.jsonl.gz"} or (
                len(name.parts) == 2
                and (
                    (name.parts[0] == "embeddings" and name.suffix == ".npz")
                    or (
                        name.parts[0] == "reviews"
                        and name.name in contract["review_samples"]
                    )
                )
            )
            if (
                not member.isfile()
                or not allowed
                or name.is_absolute()
                or ".." in name.parts
                or member.name in names
            ):
                raise ValueError(
                    f"Real cache member rule: unexpected {member.name!r}; rebuild the allowlisted archive."
                )
            names.add(member.name)
        expected_count = (
            2 + contract["embedding_batches"] + len(contract["review_samples"])
        )
        if len(names) != expected_count or not {
            "selection.json",
            "catalog.jsonl.gz",
        }.issubset(names):
            raise ValueError(
                f"Real cache members rule: found {len(names)}, expected {expected_count}; restore the complete archive."
            )
        output.mkdir(parents=True, exist_ok=True)
        archive.extractall(output, members=members, filter="data")


def restore(directory: Path, contract: dict) -> dict:
    """Load verified records and saved vectors, then build the served projection."""
    import psycopg

    from scripts.prepare_live_catalog import prepare as prepare_live
    from scripts.prepare_staged_catalog_search import prepare as prepare_search
    from scripts.stage_catalog_evidence import import_samples
    from scripts.stage_real_catalog import (
        initialize,
        load_embeddings,
        load_records,
        validate_dsn,
        verify,
    )

    selection, paths = verify_selection(directory)
    if (selection["products"], selection["catalog_sha256"], len(paths) - 2) != (
        contract["products"],
        contract["catalog_sha256"],
        contract["embedding_batches"],
    ):
        raise ValueError(
            "Real cache identity rule: selection differs from the release contract; restore the pinned archive."
        )
    samples = []
    for name, count in contract["review_samples"].items():
        state = json.loads((directory / "reviews" / name).read_text())
        category = name.removesuffix("-reviews.json")
        if (
            state["source"] != source_identity(category)
            or len(state["reviews"]) != count
        ):
            raise ValueError(
                f"Real cache review rule: {name} changed; restore the pinned sample."
            )
        for row in state["reviews"]:
            verify_review(row)
        samples.append((category, state))
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    dataset = contract["dataset_id"]
    with psycopg.connect(
        dsn, connect_timeout=20, application_name="mosaic-real-cache-restore"
    ) as connection:
        initialize(connection, dataset, selection)
        load_records(connection, dataset, directory, selection["products"])
        load_embeddings(connection, dataset, directory, selection["products"])
        report = verify(connection, dataset, directory)
        if not report["ready_for_search_validation"]:
            raise ValueError(
                f"Real cache restore rule: incomplete import {report}; resume the pinned import."
            )
        prepare_search(connection, dataset)
        prepare_live(connection, dataset)
        for category, state in samples:
            import_samples(connection, dataset, state, state["reviews"], category)
        connection.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "verify", "restore"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--reviews", type=Path, nargs="*", default=[])
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    if args.action == "export":
        if not args.selection or not args.dataset_id:
            parser.error("export requires --selection and --dataset-id")
        contract = export(args.selection, args.reviews, args.archive, args.dataset_id)
        args.contract.write_text(json.dumps(contract, indent=2) + "\n")
    else:
        contract = json.loads(args.contract.read_text())
        verify_archive(args.archive, contract)
        if args.action == "restore":
            if not args.selection:
                parser.error(
                    "restore requires --selection as an extraction destination"
                )
            unpack(args.archive, args.selection, contract)
            restore(args.selection, contract)
    print(
        json.dumps(
            {
                "action": args.action,
                "dataset_id": contract["dataset_id"],
                "products": contract["products"],
                "sha256": contract["sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
