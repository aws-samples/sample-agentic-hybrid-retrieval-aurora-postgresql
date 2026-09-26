#!/usr/bin/env python3
"""Precompute exact nearest neighbours for the HNSW instrument's query anchors.

The exact answer needs the distance from an anchor to every stored vector.
Computing it per interaction would turn an optional Labs surface into a load
generator, so it runs once here for every anchor in
`data/benchmarks/hnsw_anchors.json` across the six filter presets. Every recall
figure the instrument reports afterwards is computed against these rows, which
is what keeps the live probe's cost ceiling a filtered HNSW scan.

One pass over the catalog serves a batch of anchors: the distances from every
vector to each anchor in the batch land in a session-local table together with
the filter columns, and each preset's exact top-k per anchor is then a ranked
read of that table under the preset's own predicate text. This is the same
answer as one filtered `ORDER BY embedding <=> anchor LIMIT k` scan per pair,
at a fraction of the detoasting cost on a catalog of half a million vectors.

Idempotent, and refuses to serve or write ground truth that belongs to a
different corpus, anchor set, or preset predicate than the one connected.

Ordering and ties: the exact query orders by cosine distance and then by
`product_id`, so equal-distance rows always land in the same order. The anchor
itself is a catalog product, so it appears at rank 1 with distance 0 whenever
it passes the preset's filter; recall counts it like any other neighbour.

Usage
-----
    make db-seed-exact-neighbors
    uv run python scripts/seed_exact_neighbors.py
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
from service.catalog_runtime import product_document
from service.config import get_settings
from service.db import connect
from service.hnsw_anchors import AnchorSet, require_anchor_set_for_served_catalog
from service.hnsw_corpus import (  # noqa: F401  (re-exported for callers)
    UNRESOLVED_MANIFEST,
    StaleGroundTruth,
    assert_manifest_matches,
    corpus_manifest,
)
from service.hnsw_presets import EXACT_BASELINE_SETTINGS, FILTER_PRESETS, FilterPreset

#: Neighbours stored per anchor and preset. The probe accepts any k up to this
#: and reads a prefix, so one seeding run serves every request depth.
SEEDED_K = 50

#: Anchors whose distances one catalog pass computes together. Ten anchors
#: over 553,911 vectors is about 5.5 million distance rows in the session table.
ANCHOR_BATCH = 10

#: The service pool applies the interactive request timeout to every checkout.
#: An exact scan over every stored vector is not an interactive request, so the
#: seeder asks for its own ceiling instead of inheriting a 30-second cancel.
EXACT_SCAN_TIMEOUT_MS = 900_000


def exact_neighbors(
    connection: Any, *, embedding: Any, preset: FilterPreset, k: int
) -> list[tuple[int, int, float]]:
    """Return `(rank, product_id, cosine_distance)` from a forced exact scan.

    Both planner settings are disabled together: turning off only index scans
    leaves the bitmap path available, and the result would no longer be exact.
    """
    predicate = f"AND {preset.predicate_sql}" if preset.predicate_sql else ""
    # SET/RESET rather than SET LOCAL. `connection.transaction()` degrades to a
    # SAVEPOINT when an implicit transaction is already open, and SET LOCAL survives
    # RELEASE SAVEPOINT, so the setting leaks unpredictably. RESET in a finally
    # block cannot leak regardless of transaction nesting.
    try:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"SET {setting}")
        rows = connection.execute(
            f"""
            SELECT product_id, (embedding <=> %s) AS cosine_distance
            FROM {product_document()}
            WHERE embedding IS NOT NULL {predicate}
            ORDER BY embedding <=> %s, product_id
            LIMIT %s
            """,
            (embedding, embedding, k),
        ).fetchall()
    finally:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"RESET {setting.split(' =')[0]}")
    return [
        (rank, int(row["product_id"]), float(row["cosine_distance"]))
        for rank, row in enumerate(rows, start=1)
    ]


DISTANCE_TABLE = "pg_temp.hnsw_anchor_distance"


def compute_distances(connection: Any, anchors: list[dict[str, Any]]) -> int:
    """One pass over the catalog: every vector's distance to each anchor in `anchors`.

    The session table keeps the filter columns beside each distance so the
    preset predicates rank it with the same text the served probe appends to
    its query. Returns the number of distance rows written.
    """
    connection.execute(f"DROP TABLE IF EXISTS {DISTANCE_TABLE}")
    placeholders = ", ".join("(%s::bigint, %s::vector)" for _ in anchors)
    parameters: list[Any] = []
    for anchor in anchors:
        parameters.extend((int(anchor["product_id"]), anchor["embedding"]))
    connection.execute(
        f"""
        CREATE TEMP TABLE hnsw_anchor_distance AS
        SELECT a.anchor_product_id,
               d.product_id,
               (d.embedding <=> a.embedding) AS cosine_distance,
               d.domain, d.category_key, d.brand_name, d.rating
        FROM {product_document()} AS d
        CROSS JOIN (VALUES {placeholders}) AS a(anchor_product_id, embedding)
        WHERE d.embedding IS NOT NULL
        """,
        parameters,
    )
    return int(
        connection.execute(f"SELECT count(*) AS n FROM {DISTANCE_TABLE}").fetchone()[
            "n"
        ]
    )


def ranked_neighbors(
    connection: Any, *, preset: FilterPreset, k: int
) -> dict[int, list[tuple[int, int, float]]]:
    """Exact top-k per anchor under one preset, read from the distance table.

    Ties are ordered by `product_id`, exactly as the per-anchor query does.
    """
    predicate = f"WHERE {preset.predicate_sql}" if preset.predicate_sql else ""
    rows = connection.execute(
        f"""
        SELECT anchor_product_id, product_id, cosine_distance, rank
        FROM (
            SELECT anchor_product_id, product_id, cosine_distance,
                   row_number() OVER (
                       PARTITION BY anchor_product_id
                       ORDER BY cosine_distance, product_id
                   ) AS rank
            FROM {DISTANCE_TABLE}
            {predicate}
        ) AS ranked
        WHERE rank <= %s
        ORDER BY anchor_product_id, rank
        """,
        (k,),
    ).fetchall()
    truth: dict[int, list[tuple[int, int, float]]] = {}
    for row in rows:
        truth.setdefault(int(row["anchor_product_id"]), []).append(
            (int(row["rank"]), int(row["product_id"]), float(row["cosine_distance"]))
        )
    return truth


def _write_neighbors(
    connection: Any,
    *,
    anchor_product_id: int,
    preset: FilterPreset,
    k: int,
    manifest_sha256: str,
    anchor_set_sha256: str,
    revision: str | None,
    neighbors: list[tuple[int, int, float]],
) -> int:
    # An anchor whose filtered neighbourhood shrank leaves stale ranks behind
    # under an upsert alone, so the pair's rows are replaced as a whole.
    connection.execute(
        """
        DELETE FROM mosaic_bench.exact_neighbor
        WHERE anchor_product_id = %s AND filter_preset = %s AND k = %s
          AND dataset_manifest_sha256 = %s
        """,
        (anchor_product_id, preset.key, k, manifest_sha256),
    )
    for rank, product_id, distance in neighbors:
        connection.execute(
            """
            INSERT INTO mosaic_bench.exact_neighbor (
                anchor_product_id, filter_preset, k, dataset_manifest_sha256,
                neighbor_rank, neighbor_product_id, cosine_distance,
                source_revision, anchor_set_sha256, predicate_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                anchor_product_id,
                preset.key,
                k,
                manifest_sha256,
                rank,
                product_id,
                distance,
                revision,
                anchor_set_sha256,
                preset.predicate_sha256,
            ),
        )
    return len(neighbors)


def anchor_vectors(connection: Any, anchors: AnchorSet) -> list[dict[str, Any]]:
    """The anchors' stored vectors, refusing an anchor the catalog lacks."""
    rows = connection.execute(
        f"""
        SELECT product_id, title, embedding
        FROM {product_document()}
        WHERE product_id = ANY(%s) AND embedding IS NOT NULL
        ORDER BY product_id
        """,
        (list(anchors.product_ids),),
    ).fetchall()
    found = {int(row["product_id"]) for row in rows}
    missing = [item for item in anchors.product_ids if item not in found]
    if missing:
        raise StaleGroundTruth(
            explain(
                f"anchors {missing[:10]} are not in the served catalog with a vector",
                "select anchors from the served catalog with `make select-hnsw-anchors`",
            )
        )
    return [dict(row) for row in rows]


def seed(
    connection: Any,
    *,
    anchors: AnchorSet,
    k: int,
    manifest_sha256: str,
    revision: str | None,
) -> int:
    """Write exact neighbours for every anchor and preset. Returns rows written."""
    written = 0
    vectors = anchor_vectors(connection, anchors)
    for start in range(0, len(vectors), ANCHOR_BATCH):
        batch = vectors[start : start + ANCHOR_BATCH]
        distances = compute_distances(connection, batch)
        print(
            f"  batch {start // ANCHOR_BATCH + 1}: {len(batch)} anchors, "
            f"{distances} distance rows",
            flush=True,
        )
        for preset in FILTER_PRESETS:
            truth = ranked_neighbors(connection, preset=preset, k=k)
            for anchor in batch:
                neighbors = truth.get(int(anchor["product_id"]), [])
                written += _write_neighbors(
                    connection,
                    anchor_product_id=int(anchor["product_id"]),
                    preset=preset,
                    k=k,
                    manifest_sha256=manifest_sha256,
                    anchor_set_sha256=anchors.sha256,
                    revision=revision,
                    neighbors=neighbors,
                )
            connection.commit()
            print(
                f"    {preset.key:<13} "
                f"{sum(len(truth.get(int(a['product_id']), [])) for a in batch):>4} "
                f"neighbours across the batch",
                flush=True,
            )
    connection.execute(f"DROP TABLE IF EXISTS {DISTANCE_TABLE}")
    connection.commit()
    return written


def load_ground_truth(
    connection: Any,
    *,
    manifest_sha256: str,
    k: int,
    anchor_set_sha256: str,
    presets: tuple[FilterPreset, ...] = FILTER_PRESETS,
) -> dict[tuple[int, str], list[int]]:
    """Return `{(anchor_product_id, preset_key): [product_id in rank order]}`.

    Only rows computed for this corpus, this anchor set and each preset's
    current predicate are returned; anything else is not this question's
    ground truth. The stored depth is `SEEDED_K`; the first `k` ranks are
    returned.
    """
    if k > SEEDED_K:
        raise StaleGroundTruth(
            explain(
                f"k={k} exceeds the seeded depth {SEEDED_K}",
                f"request k <= {SEEDED_K} or reseed with a larger --k",
            )
        )
    predicates = [(preset.key, preset.predicate_sha256) for preset in presets]
    rows = connection.execute(
        """
        SELECT neighbor.anchor_product_id, neighbor.filter_preset,
               neighbor.neighbor_product_id
        FROM mosaic_bench.exact_neighbor AS neighbor
        JOIN unnest(%s::text[], %s::text[]) AS current(preset_key, predicate_sha256)
          ON current.preset_key = neighbor.filter_preset
         AND current.predicate_sha256 = neighbor.predicate_sha256
        WHERE neighbor.dataset_manifest_sha256 = %s
          AND neighbor.anchor_set_sha256 = %s
          AND neighbor.k = %s
          AND neighbor.neighbor_rank <= %s
        ORDER BY neighbor.anchor_product_id, neighbor.filter_preset,
                 neighbor.neighbor_rank
        """,
        (
            [key for key, _ in predicates],
            [digest for _, digest in predicates],
            manifest_sha256,
            anchor_set_sha256,
            SEEDED_K,
            k,
        ),
    ).fetchall()
    truth: dict[tuple[int, str], list[int]] = {}
    for row in rows:
        key = (int(row["anchor_product_id"]), row["filter_preset"])
        truth.setdefault(key, []).append(int(row["neighbor_product_id"]))
    return truth


def report_coverage(
    connection: Any, *, anchors: AnchorSet, manifest: str, k: int
) -> int:
    """Print how many anchor/preset pairs hold ground truth; non-zero if any lack it.

    A pair whose exact result set is empty is not missing: an empty
    neighbourhood is a measured answer, and it is stored as zero rows only
    when the seeder ran for it. This report therefore counts pairs the seeder
    wrote at least one row for and names the rest so a reader can tell an
    unseeded pair from an empty one by re-running the seeder.
    """
    truth = load_ground_truth(
        connection, manifest_sha256=manifest, k=k, anchor_set_sha256=anchors.sha256
    )
    expected = len(FILTER_PRESETS) * len(anchors.product_ids)
    print(f"ground truth: {len(truth)} of {expected} anchor/preset pairs")
    if len(truth) != expected:
        print(
            explain(
                f"{expected - len(truth)} pair(s) missing for corpus {manifest[:12]} "
                f"and anchor set {anchors.sha256[:12]}",
                "run `make db-seed-exact-neighbors`",
            )
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=SEEDED_K)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report coverage and exit non-zero if incomplete. Writes nothing.",
    )
    arguments = parser.parse_args()
    if arguments.k < 1:
        raise SystemExit(
            explain(f"--k {arguments.k}", "pass a positive --k, for example 50")
        )
    if arguments.k != SEEDED_K:
        raise SystemExit(
            explain(
                f"--k {arguments.k} differs from the seeded depth {SEEDED_K}",
                "change SEEDED_K in this script so the probe and the seeder agree",
            )
        )
    anchors = require_anchor_set_for_served_catalog()
    settings = get_settings()
    with connect(statement_timeout_ms=EXACT_SCAN_TIMEOUT_MS) as connection:
        manifest = corpus_manifest(connection)
        if anchors.catalog_sha256 and anchors.catalog_sha256 != manifest:
            raise SystemExit(
                explain(
                    f"the anchor set was selected on catalog {anchors.catalog_sha256[:12]} "
                    f"but the connected catalog is {manifest[:12]}",
                    "run `make select-hnsw-anchors` against the connected catalog",
                )
            )
        if arguments.check:
            raise SystemExit(
                report_coverage(
                    connection, anchors=anchors, manifest=manifest, k=arguments.k
                )
            )
        written = seed(
            connection,
            anchors=anchors,
            k=arguments.k,
            manifest_sha256=manifest,
            revision=settings.source_revision,
        )
    print(
        f"wrote {written} exact neighbour rows for corpus {manifest} and anchor set "
        f"{anchors.sha256}"
    )


if __name__ == "__main__":
    main()
