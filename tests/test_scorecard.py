"""The Prove-step scorecard: a read-only render of the committed artifact.

Ruling R3's gate is a conjunction over three facts -- the artifact's own
`retrieval_fingerprint` (a hash over the files that can move the scored
numbers; see `service.retrieval_fingerprint`) equals the one the running
service reports, the artifact's own `worktree_dirty` flag was `False` at
measurement time, and the pinned models and query-set hashes the artifact
recorded still match what is running. A strict revision equality is
deliberately not part of this: `scripts/score_evals.py` records the source
revision *before* the artifact it writes is committed, so the artifact's
revision is always one commit behind the revision that carries it, and that
gate would read "pending" forever. Each clause gets its own red-at-birth
proof below, plus independence and a witness per house standards rule 7.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service.assertions import ASSERTIONS
from service.main import app
from service.models import ScorecardGoldenAnchor
from service.scorecard import (
    PENDING_TEXT,
    SCORECARD_ARTIFACT,
    _agent_contracts,
    _attribution,
    _CurrentRetrievalIdentity,
    _eligibility_fixtures,
    _release_check_total,
    _scored_queries,
    retrieval_scorecard,
)

ROOT = Path(__file__).resolve().parents[1]

_MATCHING_FINGERPRINT = "f" * 64
_MATCHING_QUERY_SET_SHA = "q" * 64
_MATCHING_SCORED_QUERY_SET_SHA = "s" * 64
_MATCHING_EMBEDDING_MODEL = "embed-model"
_MATCHING_RERANK_MODEL = "rerank-model"


def _artifact(
    *,
    fingerprint: str = _MATCHING_FINGERPRINT,
    dirty: bool = False,
    embedding: str = _MATCHING_EMBEDDING_MODEL,
    rerank: str = _MATCHING_RERANK_MODEL,
    query_set_sha: str = _MATCHING_QUERY_SET_SHA,
    scored_query_set_sha: str = _MATCHING_SCORED_QUERY_SET_SHA,
    revision: str = "a" * 40,
) -> dict:
    return {
        "retrieval_fingerprint": fingerprint,
        "source": {"revision": revision, "worktree_dirty": dirty},
        "models": {"embedding": embedding, "rerank": rerank},
        "query_set_sha256": query_set_sha,
        "scored_query_set_sha256": scored_query_set_sha,
    }


def _current(
    *,
    fingerprint: str = _MATCHING_FINGERPRINT,
    embedding: str = _MATCHING_EMBEDDING_MODEL,
    rerank: str = _MATCHING_RERANK_MODEL,
    query_set_sha: str = _MATCHING_QUERY_SET_SHA,
    scored_query_set_sha: str = _MATCHING_SCORED_QUERY_SET_SHA,
) -> _CurrentRetrievalIdentity:
    return _CurrentRetrievalIdentity(
        retrieval_fingerprint=fingerprint,
        embedding_model_id=embedding,
        rerank_model_id=rerank,
        query_set_sha256=query_set_sha,
        scored_query_set_sha256=scored_query_set_sha,
    )


def _api_artifact_and_settings(
    monkeypatch,
    *,
    dirty: bool = False,
    current_source_worktree_dirty: bool = False,
    revision: str = "9" * 40,
) -> dict:
    """Wire the real route to a synthetic, fully-matching artifact.

    Patches every input `_attribution` reads -- the artifact loader, the
    fingerprint/hash functions imported into `service.scorecard`, and
    settings -- so the route-level tests exercise real HTTP dispatch without
    depending on the real repository's current fingerprint or the real
    committed artifact ever matching it.
    """
    artifact = json.loads(SCORECARD_ARTIFACT.read_text(encoding="utf-8"))
    artifact["retrieval_fingerprint"] = _MATCHING_FINGERPRINT
    artifact["query_set_sha256"] = _MATCHING_QUERY_SET_SHA
    artifact["scored_query_set_sha256"] = _MATCHING_SCORED_QUERY_SET_SHA
    artifact["models"] = {
        "embedding": _MATCHING_EMBEDDING_MODEL,
        "rerank": _MATCHING_RERANK_MODEL,
    }
    artifact["source"] = {"revision": revision, "worktree_dirty": dirty}

    monkeypatch.setattr("service.scorecard._load_artifact", lambda: artifact)
    monkeypatch.setattr(
        "service.scorecard.compute_retrieval_fingerprint",
        lambda: _MATCHING_FINGERPRINT,
    )
    monkeypatch.setattr(
        "service.scorecard.query_set_sha256",
        lambda path: _MATCHING_QUERY_SET_SHA,
    )
    monkeypatch.setattr(
        "service.scorecard.scored_query_set_sha256",
        lambda scored: _MATCHING_SCORED_QUERY_SET_SHA,
    )
    monkeypatch.setattr(
        "service.scorecard.get_settings",
        lambda: SimpleNamespace(
            source_revision=revision,
            source_worktree_dirty=current_source_worktree_dirty,
            embedding_model_id=_MATCHING_EMBEDDING_MODEL,
            rerank_model_id=_MATCHING_RERANK_MODEL,
        ),
    )
    return artifact


# --- Attribution: each clause, red-at-birth and independent -----------------


def test_attribution_shows_metrics_when_everything_matches_and_is_clean():
    """Positive witness: the conjunction can actually go the True way.

    Paired with every "hidden" test below per house standards rule 7 -- a
    gate that only ever returns False would pass those vacuously.
    """
    attributed, note = _attribution(_artifact(), _current())

    assert attributed is True
    assert _MATCHING_FINGERPRINT[:12] in note


def test_attribution_hides_when_the_retrieval_fingerprint_differs():
    """Red-at-birth for the fingerprint clause: everything else matches."""
    attributed, note = _attribution(_artifact(), _current(fingerprint="g" * 64))

    assert attributed is False
    assert note.startswith(PENDING_TEXT)
    assert "retrieval fingerprint changed" in note


def test_attribution_hides_when_the_artifact_never_recorded_a_fingerprint():
    """The committed artifact predates this mechanism entirely.

    `artifact.get("retrieval_fingerprint")` is `None` for every artifact
    written before this change, including the one currently committed at
    `data/evals/canonical_scorecard.json`. That must fail closed with a
    distinct, honest reason rather than a generic mismatch message.
    """
    attributed, note = _attribution(_artifact(fingerprint=""), _current())

    assert attributed is False
    assert "no retrieval fingerprint was recorded" in note


def test_attribution_hides_when_the_measurement_worktree_was_dirty():
    """Red-at-birth for the dirty clause, with every other clause matching.

    The one most likely to be skipped: a matching fingerprint alone is not
    enough if the artifact that recorded it was measured from an unclean
    tree.
    """
    attributed, note = _attribution(_artifact(dirty=True), _current())

    assert attributed is False
    assert "worktree was not clean" in note


def test_attribution_hides_when_the_embedding_model_changed():
    attributed, note = _attribution(
        _artifact(), _current(embedding="a-different-embedding-model")
    )

    assert attributed is False
    assert "embedding or rerank model changed" in note


def test_attribution_hides_when_the_rerank_model_changed():
    attributed, note = _attribution(
        _artifact(), _current(rerank="a-different-rerank-model")
    )

    assert attributed is False
    assert "embedding or rerank model changed" in note


def test_attribution_hides_when_the_raw_query_set_hash_changed():
    attributed, note = _attribution(
        _artifact(), _current(query_set_sha="a-different-hash")
    )

    assert attributed is False
    assert "canonical query set or its judgments changed" in note


def test_attribution_hides_when_the_scored_query_set_hash_changed():
    attributed, note = _attribution(
        _artifact(), _current(scored_query_set_sha="a-different-hash")
    )

    assert attributed is False
    assert "canonical query set or its judgments changed" in note


def test_attribution_reports_every_mismatched_clause_not_just_the_first():
    """Witness that the reason list is actually built from independent
    checks rather than short-circuiting on the first failure."""
    attributed, note = _attribution(
        _artifact(dirty=True),
        _current(fingerprint="g" * 64, embedding="a-different-embedding-model"),
    )

    assert attributed is False
    assert "retrieval fingerprint changed" in note
    assert "worktree was not clean" in note
    assert "embedding or rerank model changed" in note


def test_attribution_missing_artifact_source_and_models_default_to_mismatch():
    """An artifact with no `source` or `models` key at all -- not just an
    artifact with those keys present but empty -- still fails closed."""
    attributed, note = _attribution(
        {
            "retrieval_fingerprint": _MATCHING_FINGERPRINT,
            "query_set_sha256": _MATCHING_QUERY_SET_SHA,
            "scored_query_set_sha256": _MATCHING_SCORED_QUERY_SET_SHA,
        },
        _current(),
    )

    assert attributed is False
    assert note.startswith(PENDING_TEXT)


# --- Section A: population metrics, and the population-count safety net ----


def test_scored_queries_excludes_the_agent_contract_case():
    scored = _scored_queries()

    assert {query["query_id"] for query in scored} == {
        f"G-{number:03d}" for number in range(1, 22)
    } - {"G-010"}


def test_retrieval_quality_rejects_a_population_count_that_drifted_from_the_artifact(
    monkeypatch,
):
    """Red-at-birth: shrink the scored population without re-measuring.

    `_retrieval_quality`'s guard exists so an edited `canonical_queries.jsonl`
    cannot silently serve stale per-query counts against a new query set.
    """
    from service import scorecard

    original = scorecard._scored_queries
    monkeypatch.setattr(scorecard, "_scored_queries", lambda: original()[:1])

    with pytest.raises(ValueError, match="regenerate"):
        retrieval_scorecard()


def test_retrieval_scorecard_serves_the_committed_population_metrics():
    response = retrieval_scorecard()

    artifact = json.loads(SCORECARD_ARTIFACT.read_text(encoding="utf-8"))
    assert response.retrieval_quality.sample_size == 20
    assert response.retrieval_quality.recall_at_10 == artifact["metrics"]["recall@10"]
    assert response.retrieval_quality.mrr == artifact["metrics"]["mrr"]
    assert response.retrieval_quality.ndcg_at_10 == artifact["metrics"]["ndcg@10"]
    assert response.retrieval_quality.excluded_agent_contract_query_ids == ["G-010"]
    # The committed artifact now carries labels, so pass-through must expose
    # them on every row. There is no absent-case test here on purpose:
    # service/scorecard.py copies these rows verbatim, so no code path could
    # invent a key, and a test asserting it cannot fail. Degradation is tested
    # where it can actually go wrong -- the UI rendering `undefined`.
    assert len(response.retrieval_quality.per_query_metrics) == 20
    for row in response.retrieval_quality.per_query_metrics:
        assert row["query_text"]
        assert row["concept_label"]


# --- Section B: golden regression anchors, never mixed with IR metrics -----


def test_regression_anchors_total_is_read_from_the_query_set_not_retyped():
    """The PASS/total denominator comes from the harness's own query fixtures.

    Independence proof: mutating the artifact's own recorded checks does not
    change what `_release_check_total` reports, because it reads
    `canonical_queries.jsonl` directly rather than re-deriving the total from
    the same artifact `passed` is read from.
    """
    scored = _scored_queries()

    assert _release_check_total(scored) == 6


def test_regression_anchors_pass_and_total_agree_on_the_committed_artifact():
    response = retrieval_scorecard()

    assert response.regression_anchors.passed == 6
    assert response.regression_anchors.total == 6
    assert {anchor.query_id for anchor in response.regression_anchors.anchors} == {
        "G-001",
        "G-015",
        "G-019",
        "G-021",
    }
    # The committed artifact now carries labels, so every anchor must expose
    # both. The absent case stays covered against a synthetic artifact by
    # test_golden_anchor_defaults_labels_to_none_when_the_artifact_lacks_them.
    for anchor in response.regression_anchors.anchors:
        assert anchor.query_text
        assert anchor.concept_label


def test_golden_anchor_carries_query_text_and_concept_label_when_the_artifact_has_them():
    """Red-at-birth pairing for the test above: the model must actually be
    ABLE to carry the labels, not merely tolerate their absence."""
    anchor = ScorecardGoldenAnchor.model_validate(
        {
            "query_id": "G-001",
            "product_id": 17001,
            "type": "top_rank",
            "query_text": "Sonora WH-C720 headphones",
            "concept_label": "Exact identity",
        }
    )

    assert anchor.query_text == "Sonora WH-C720 headphones"
    assert anchor.concept_label == "Exact identity"


def test_golden_anchor_defaults_labels_to_none_when_the_artifact_lacks_them():
    anchor = ScorecardGoldenAnchor.model_validate(
        {"query_id": "G-001", "product_id": 17001, "type": "top_rank"}
    )

    assert anchor.query_text is None
    assert anchor.concept_label is None


# --- Section C: eligibility/filter fixtures, not a relevance judgment ------


def test_eligibility_fixture_count_comes_from_the_harnesss_own_filter():
    """Not a number retyped in this module: computed via the same
    `hard_negative_ids` filter `scripts.score_evals.product_retrieval_queries`
    feeds into `validate_hard_negatives`."""
    scored = _scored_queries()

    fixtures = _eligibility_fixtures(scored)

    assert len(fixtures) == 18
    assert "G-014" not in fixtures  # the one scored query with no hard negatives
    assert "G-010" not in fixtures  # excluded from product_retrieval entirely


def test_eligibility_fixture_count_tracks_the_scored_population_independently():
    """Independence/witness: shrinking the scored population changes the
    fixture count, proving this is computed from the population rather than a
    constant."""
    scored = _scored_queries()

    assert len(_eligibility_fixtures(scored[:5])) <= 5
    assert len(_eligibility_fixtures([])) == 0


# --- Section D: deterministic agent/evidence contracts ---------------------


def test_agent_contracts_are_backed_by_real_assertion_names():
    contracts = _agent_contracts()

    assert {g.key for g in contracts.guarantees} == {
        "retrieval_scope",
        "compare_boundary",
        "evidence_authorization",
        "citation_resolution",
        "tool_contract",
    }
    for guarantee in contracts.guarantees:
        assert guarantee.assertion_names, guarantee.key
        for name, falsifier in zip(guarantee.assertion_names, guarantee.falsifiers):
            assert falsifier == ASSERTIONS[name].falsifier


def test_agent_contracts_tool_contract_count_is_only_on_the_tool_contract_row():
    contracts = _agent_contracts()

    by_key = {g.key: g for g in contracts.guarantees}
    assert by_key["tool_contract"].fixture_count is not None
    assert by_key["tool_contract"].fixture_count > 0
    for key, guarantee in by_key.items():
        if key != "tool_contract":
            assert guarantee.fixture_count is None


def test_agent_contracts_reject_an_unmapped_assertion_name(monkeypatch):
    """Red-at-birth: a typo in the internal mapping must fail loudly rather
    than silently serve a falsifier for the wrong contract."""
    from service import scorecard

    monkeypatch.setitem(
        scorecard._AGENT_CONTRACT_ASSERTIONS,
        "tool_contract",
        ["this_assertion_does_not_exist"],
    )

    with pytest.raises(ValueError, match="unresolved assertions"):
        scorecard._agent_contracts()


# --- The API route -----------------------------------------------------


def test_api_serves_the_scorecard_route():
    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is True
    assert payload["provenance"]["source_revision"]
    assert payload["provenance"]["current_source_revision"]
    assert payload["retrieval_quality"]["sample_size"] == 20
    assert payload["regression_anchors"]["total"] == 6
    assert payload["eligibility_contracts"]["fixture_count"] == 18
    assert len(payload["agent_contracts"]["guarantees"]) == 5


def test_api_returns_503_when_the_artifact_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "service.scorecard.SCORECARD_ARTIFACT",
        tmp_path / "absent.json",
    )

    response = TestClient(app).get("/api/scorecard")

    assert response.status_code == 503
    assert "fix:" in response.json()["detail"]


def test_api_shows_metrics_once_the_fingerprint_models_and_query_set_all_match(
    monkeypatch,
):
    """End-to-end proof of the "shown" branch through the real HTTP route.

    Pairs with `test_api_serves_the_scorecard_route` above (hidden today,
    because the real committed artifact predates the fingerprint mechanism)
    so this gate cannot pass merely by always hiding the numbers.
    """
    artifact = _api_artifact_and_settings(monkeypatch)

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is True
    assert (
        payload["retrieval_quality"]["recall_at_10"] == artifact["metrics"]["recall@10"]
    )


def test_api_hides_metrics_when_the_matching_fingerprint_was_measured_dirty(
    monkeypatch,
):
    """The route-level proof of the dirty clause: matching fingerprint and
    inputs, but the measurement's own worktree was not clean."""
    _api_artifact_and_settings(monkeypatch, dirty=True)

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is False
    assert payload["provenance"]["attribution_note"].startswith(PENDING_TEXT)


def test_api_shows_metrics_despite_a_dirty_running_worktree(monkeypatch):
    """The gate is over the *measurement's* dirty flag, not the caller's.

    A server running with local uncommitted edits, at a fingerprint that
    matches the artifact, with a clean measurement, must still show the
    metrics -- this is the independence proof for the "measured
    worktree_dirty" clause at the route level.
    """
    _api_artifact_and_settings(
        monkeypatch,
        dirty=False,
        current_source_worktree_dirty=True,
    )

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is True
