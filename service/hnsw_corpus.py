"""Which corpus the HNSW instrument's ground truth belongs to.

Ground truth is only valid for the corpus that produced it. The legacy catalog
is identified by the checked-in dataset manifest; a prepared real catalog is
identified by the `catalog_sha256` its restore receipt records, which binds the
served rows and vectors to the release contract. Both are immutable identifiers
and neither is user-facing text.
"""

from __future__ import annotations

from typing import Any

from scripts.retrieval_profile import explain
from service.catalog_runtime import active_dataset
from service.config import get_settings

# service.config falls back to this when no manifest could be resolved. Pinning
# ground truth to it would make every unresolved run look like the same corpus.
UNRESOLVED_MANIFEST = "unknown"


class StaleGroundTruth(RuntimeError):
    """Stored ground truth does not belong to the connected corpus."""


def assert_manifest_matches(*, stored: str, connected: str) -> None:
    """Refuse ground truth computed against a different corpus.

    Args:
        stored: Corpus identity recorded alongside the neighbour rows.
        connected: Corpus identity of the corpus now connected.

    Raises:
        StaleGroundTruth: The two differ, or the connected value is missing or the
            unresolved sentinel.
    """
    if not connected or connected == UNRESOLVED_MANIFEST:
        raise StaleGroundTruth(
            explain(
                f"the connected corpus reports dataset manifest {connected!r}",
                "set DATASET_MANIFEST_SHA256, or restore data/full/manifest.json; "
                "ground truth pinned to an unresolved manifest matches any corpus",
            )
        )
    if stored != connected:
        raise StaleGroundTruth(
            explain(
                f"ground truth was computed for corpus {stored} but the connected "
                f"corpus is {connected}",
                "re-run `make db-seed-exact-neighbors`; recall computed against "
                "another corpus is not recall",
            )
        )


def corpus_manifest(connection: Any) -> str:
    """The connected corpus's identity, refused unless it is resolved.

    For a prepared real catalog this is the restore receipt's `catalog_sha256`,
    read from the cluster so it describes the rows actually served. For the
    legacy catalog it is the checked-in dataset manifest.

    Raises:
        StaleGroundTruth: The receipt is absent or names another dataset, or the
            legacy manifest is empty or the unresolved sentinel.
    """
    dataset = active_dataset()
    if dataset:
        row = connection.execute(
            "SELECT dataset_id, catalog_sha256 FROM mosaic_live_search.receipt "
            "WHERE singleton"
        ).fetchone()
        if row is None or row["dataset_id"] != dataset or not row["catalog_sha256"]:
            raise StaleGroundTruth(
                explain(
                    f"the connected cluster serves no verified receipt for {dataset!r}",
                    "complete the catalog's verified preparation before seeding or "
                    "probing ground truth",
                )
            )
        return str(row["catalog_sha256"])
    manifest = get_settings().dataset_manifest_sha256 or ""
    assert_manifest_matches(stored=manifest, connected=manifest)
    return manifest
