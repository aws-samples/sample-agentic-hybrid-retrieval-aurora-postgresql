"""`GET /api/readiness` names the build and corpus that answered.

The Playground's readiness strip shows nine facts about the room, two of which,
the running source revision and the dataset manifest hash, come from settings
rather than from Aurora. Before 2026-09-04 no route exposed them and the strip
printed `not checked` for both, permanently.
"""

from __future__ import annotations

from service import main


def _database_stub() -> dict[str, object]:
    return {
        "schema_ready": True,
        "product_count": 500000,
        "embedded_product_count": 500000,
        "premium_product_count": 120,
        "evidence_product_count": 500000,
        "missing_retrieval_indexes": None,
        "missing_retrieval_functions": None,
        "embedding_model_ids": [],
        "exact_neighbor_ground_truth": "missing",
    }


def test_readiness_reports_the_running_source_and_manifest(monkeypatch) -> None:
    monkeypatch.setattr(main, "readiness", _database_stub)
    monkeypatch.setattr(
        main, "bedrock_credentials_status", lambda _region: {"ready": True}
    )

    payload = main.get_readiness()

    source = payload["source"]
    assert source["revision"] == main.settings.source_revision
    assert source["worktree_dirty"] == main.settings.source_worktree_dirty
    assert source["dataset_manifest_sha256"] == main.settings.dataset_manifest_sha256
    assert set(source) == {"revision", "worktree_dirty", "dataset_manifest_sha256"}
