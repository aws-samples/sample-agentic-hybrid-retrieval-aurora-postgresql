"""The query anchors the HNSW instrument measures, as a committed contract.

Anchors are real catalog products whose stored vectors serve as query vectors.
They are chosen once by `scripts/select_hnsw_anchors.py`, which records the
selection algorithm, seed, sample sizes and the resulting ids in
`data/benchmarks/hnsw_anchors.json`, and are never marked on the product rows
themselves: the catalog records stay exactly what the source published.

Everything that needs anchors reads this file: the exact-neighbour seeder, the
benchmark runners and the served `/api/hnsw` routes. The file names the dataset
it was selected for, so ground truth and measurements can be refused when the
served catalog is a different one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.retrieval_profile import explain
from service.catalog_runtime import SYNTHETIC_DATASET_ID, active_dataset

ROOT = Path(__file__).resolve().parents[1]
ANCHOR_FILE = ROOT / "data" / "benchmarks" / "hnsw_anchors.json"
ANCHOR_SET_KIND = "hnsw_anchor_set"


class AnchorSetError(RuntimeError):
    """The anchor set is missing, malformed, or belongs to another catalog."""


def anchor_ids_sha256(product_ids: list[int] | tuple[int, ...]) -> str:
    """Identity of an anchor set: the sorted ids, nothing else."""
    encoded = json.dumps(sorted(int(item) for item in product_ids)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AnchorSet:
    """A verified anchor set.

    Attributes:
        dataset_id: The catalog the anchors were selected from.
        catalog_sha256: That catalog's release identity when selected.
        sha256: `anchor_ids_sha256` of the ids, which the file must restate.
        product_ids: Served product ids, in the file's order.
        anchors: The file's anchor records, for display.
        selection: How the set was chosen: algorithm, seed, sizes.
    """

    dataset_id: str
    catalog_sha256: str
    sha256: str
    product_ids: tuple[int, ...]
    anchors: tuple[dict[str, Any], ...]
    selection: dict[str, Any]

    def __contains__(self, product_id: object) -> bool:
        return product_id in set(self.product_ids)


def load_anchor_set(path: Path = ANCHOR_FILE) -> AnchorSet:
    """Read and verify the committed anchor set.

    Raises:
        AnchorSetError: The file is missing, is not an anchor set, holds no
            anchors, repeats an id, or restates a hash that does not match its
            ids.
    """
    if not path.exists():
        raise AnchorSetError(
            explain(
                f"no anchor set at {path.name}",
                "run `make select-hnsw-anchors` against the served catalog",
            )
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != ANCHOR_SET_KIND:
        raise AnchorSetError(
            explain(
                f"{path.name} has kind {payload.get('kind')!r}",
                f"regenerate it; the instrument reads only {ANCHOR_SET_KIND!r}",
            )
        )
    anchors = payload.get("anchors") or []
    ids = [int(item["product_id"]) for item in anchors]
    if not ids:
        raise AnchorSetError(
            explain(
                f"{path.name} lists no anchors",
                "run `make select-hnsw-anchors`; an empty anchor set measures nothing",
            )
        )
    if len(set(ids)) != len(ids):
        raise AnchorSetError(
            explain(f"{path.name} repeats an anchor id", "regenerate the anchor set")
        )
    expected = anchor_ids_sha256(ids)
    if payload.get("sha256") != expected:
        raise AnchorSetError(
            explain(
                f"{path.name} restates sha256 {str(payload.get('sha256'))[:12]} but "
                f"its ids hash to {expected[:12]}",
                "regenerate the anchor set rather than editing it by hand",
            )
        )
    dataset_id = str(payload.get("dataset_id") or "")
    if not dataset_id:
        raise AnchorSetError(
            explain(f"{path.name} names no dataset_id", "regenerate the anchor set")
        )
    return AnchorSet(
        dataset_id=dataset_id,
        catalog_sha256=str(payload.get("catalog_sha256") or ""),
        sha256=expected,
        product_ids=tuple(ids),
        anchors=tuple(anchors),
        selection=dict(payload.get("selection") or {}),
    )


def served_dataset_id() -> str:
    """The catalog identity the running service serves."""
    return active_dataset() or SYNTHETIC_DATASET_ID


def require_anchor_set_for_served_catalog(path: Path = ANCHOR_FILE) -> AnchorSet:
    """Load the anchor set and refuse it when it was selected for another catalog.

    Raises:
        AnchorSetError: The set is invalid, or its `dataset_id` is not the
            served catalog's.
    """
    anchors = load_anchor_set(path)
    served = served_dataset_id()
    if anchors.dataset_id != served:
        raise AnchorSetError(
            explain(
                f"the anchor set was selected from {anchors.dataset_id!r} but the "
                f"served catalog is {served!r}",
                "run `make select-hnsw-anchors` against the served catalog, then "
                "`make db-seed-exact-neighbors`",
            )
        )
    return anchors
