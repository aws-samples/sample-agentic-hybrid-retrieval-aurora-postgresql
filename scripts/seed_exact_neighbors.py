#!/usr/bin/env python3
"""Precompute exact nearest neighbours for the HNSW instrument's query anchors.

The exact query is a sequential scan over 3,870 MB of TOASTed vectors — measured
2,355 ms p50 and 2,300,855 shared buffer hits on the workshop cluster. Running it
per interaction would turn an optional Labs surface into a load generator, so it
runs once here: 30 retrieval anchors across 6 filter presets, roughly 7 minutes.
Every recall figure the instrument reports afterwards is computed against these
rows, which is what keeps the live probe's cost ceiling a filtered HNSW scan.

Idempotent, and refuses to serve or write ground truth that belongs to a different
corpus than the one connected.

Usage
-----
    make db-seed-exact-neighbors
    uv run python scripts/seed_exact_neighbors.py --k 10
    uv run python scripts/seed_exact_neighbors.py --check   # verify, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain
from service.config import get_settings
from service.db import connect
from service.hnsw_presets import (
    ANCHOR_PREDICATE,
    EXACT_BASELINE_SETTINGS,
    FILTER_PRESETS,
    FilterPreset,
)

# service.config falls back to this when no manifest could be resolved. Pinning
# ground truth to it would make every unresolved run look like the same corpus.
UNRESOLVED_MANIFEST = "unknown"


class StaleGroundTruth(RuntimeError):
    """Stored ground truth does not belong to the connected corpus."""


def assert_manifest_matches(*, stored: str, connected: str) -> None:
    """Refuse ground truth computed against a different corpus.

    Args:
        stored: Manifest sha256 recorded alongside the neighbour rows.
        connected: Manifest sha256 of the corpus now connected.

    Raises:
        StaleGroundTruth: The two differ, or the connected value is missing or the
            unresolved sentinel.
    """
    if not connected or connected == UNRESOLVED_MANIFEST:
        raise StaleGroundTruth(
            explain(
                f"the connected corpus reports dataset manifest {connected!r}",
                "set DATASET_MANIFEST_SHA256, or restore data/full/manifest.json — "
                "ground truth pinned to an unresolved manifest matches any corpus",
            )
        )
    if stored != connected:
        raise StaleGroundTruth(
            explain(
                f"ground truth was computed for manifest {stored} but the connected "
                f"corpus is {connected}",
                "re-run `make db-seed-exact-neighbors`; recall computed against "
                "another corpus is not recall",
            )
        )


def exact_neighbors(
    connection: Any, *, anchor: dict[str, Any], preset: FilterPreset, k: int
) -> list[tuple[int, int, float]]:
    """Return `(rank, product_id, cosine_distance)` from a forced exact scan.

    Both planner settings are disabled together: turning off only index scans leaves
    the bitmap path available, and the result would no longer be exact.
    """
    predicate = f"AND {preset.predicate_sql}" if preset.predicate_sql else ""
    # SET/RESET rather than SET LOCAL. `connection.transaction()` degrades to a
    # SAVEPOINT when an implicit transaction is already open, and SET LOCAL survives
    # RELEASE SAVEPOINT, so the setting leaks unpredictably. It happens to be
    # harmless here — this script only ever wants exact scans — but relying on that
    # is how the benchmark silently recorded sequential scans as ANN measurements.
    try:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"SET {setting}")
        rows = connection.execute(
            f"""
            SELECT product_id, (embedding <=> %s) AS cosine_distance
            FROM mosaic_search.product_document
            WHERE embedding IS NOT NULL {predicate}
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (anchor["embedding"], anchor["embedding"], k),
        ).fetchall()
    finally:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"RESET {setting.split(' =')[0]}")
    return [
        (rank, int(row["product_id"]), float(row["cosine_distance"]))
        for rank, row in enumerate(rows, start=1)
    ]


def _write_neighbors(
    connection: Any,
    *,
    anchor_product_id: int,
    preset_key: str,
    k: int,
    manifest_sha256: str,
    revision: str | None,
    neighbors: list[tuple[int, int, float]],
) -> int:
    for rank, product_id, distance in neighbors:
        connection.execute(
            """
            INSERT INTO mosaic_bench.exact_neighbor (
                anchor_product_id, filter_preset, k, dataset_manifest_sha256,
                neighbor_rank, neighbor_product_id, cosine_distance, source_revision
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                anchor_product_id, filter_preset, k, dataset_manifest_sha256,
                neighbor_rank
            ) DO UPDATE
            SET neighbor_product_id = EXCLUDED.neighbor_product_id,
                cosine_distance = EXCLUDED.cosine_distance,
                computed_at = now(),
                source_revision = EXCLUDED.source_revision
            """,
            (
                anchor_product_id,
                preset_key,
                k,
                manifest_sha256,
                rank,
                product_id,
                distance,
                revision,
            ),
        )
    return len(neighbors)


def seed(connection: Any, *, k: int, manifest_sha256: str, revision: str | None) -> int:
    """Write exact neighbours for every anchor and preset. Returns rows written."""
    anchors = connection.execute(
        f"""
        SELECT product_id, title, embedding
        FROM mosaic_search.product_document
        WHERE embedding IS NOT NULL AND {ANCHOR_PREDICATE}
        ORDER BY product_id
        """
    ).fetchall()
    if not anchors:
        raise SystemExit(
            explain(
                f"no products satisfy {ANCHOR_PREDICATE}",
                "load the premium cohort so the instrument has query anchors",
            )
        )

    written = 0
    for anchor in anchors:
        for preset in FILTER_PRESETS:
            neighbors = exact_neighbors(connection, anchor=anchor, preset=preset, k=k)
            written += _write_neighbors(
                connection,
                anchor_product_id=int(anchor["product_id"]),
                preset_key=preset.key,
                k=k,
                manifest_sha256=manifest_sha256,
                revision=revision,
                neighbors=neighbors,
            )
            connection.commit()
            print(
                f"  {anchor['product_id']:>7} {preset.key:<15} "
                f"{len(neighbors):>2} neighbours",
                flush=True,
            )
    return written


def load_ground_truth(
    connection: Any, *, manifest_sha256: str, k: int
) -> dict[tuple[int, str], list[int]]:
    """Return `{(anchor_product_id, preset_key): [product_id in rank order]}`."""
    rows = connection.execute(
        """
        SELECT anchor_product_id, filter_preset, neighbor_product_id
        FROM mosaic_bench.exact_neighbor
        WHERE dataset_manifest_sha256 = %s AND k = %s
        ORDER BY anchor_product_id, filter_preset, neighbor_rank
        """,
        (manifest_sha256, k),
    ).fetchall()
    truth: dict[tuple[int, str], list[int]] = {}
    for row in rows:
        key = (int(row["anchor_product_id"]), row["filter_preset"])
        truth.setdefault(key, []).append(int(row["neighbor_product_id"]))
    return truth


def _report_coverage(connection: Any, *, manifest: str, k: int) -> int:
    truth = load_ground_truth(connection, manifest_sha256=manifest, k=k)
    anchors = connection.execute(
        f"""
        SELECT count(*) AS n FROM mosaic_search.product_document
        WHERE embedding IS NOT NULL AND {ANCHOR_PREDICATE}
        """
    ).fetchone()["n"]
    expected = len(FILTER_PRESETS) * int(anchors)
    print(f"ground truth: {len(truth)} of {expected} anchor/preset pairs")
    if len(truth) != expected:
        print(
            explain(
                f"{expected - len(truth)} pair(s) missing for manifest {manifest}",
                "run `make db-seed-exact-neighbors`",
            )
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report coverage and exit non-zero if incomplete. Writes nothing.",
    )
    arguments = parser.parse_args()
    if arguments.k < 1:
        raise SystemExit(
            explain(f"--k {arguments.k}", "pass a positive --k, for example 10")
        )

    settings = get_settings()
    manifest = settings.dataset_manifest_sha256 or ""
    assert_manifest_matches(stored=manifest, connected=manifest)

    with connect() as connection:
        if arguments.check:
            raise SystemExit(
                _report_coverage(connection, manifest=manifest, k=arguments.k)
            )
        written = seed(
            connection,
            k=arguments.k,
            manifest_sha256=manifest,
            revision=settings.source_revision,
        )
    print(f"wrote {written} exact neighbour rows for manifest {manifest}")


if __name__ == "__main__":
    main()
