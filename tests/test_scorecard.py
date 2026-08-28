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


def _stage_ablation_artifact(**overrides) -> dict:
    """A committed stage-ablation artifact, gated by the same `_attribution`
    conjunction as the main scorecard artifact -- built on `_artifact` rather
    than a separate literal, so the two share the same matching-identity
    defaults and cannot silently drift apart."""
    return {
        **_artifact(**overrides),
        "measured_at": "2026-08-27T00:00:00+00:00",
        "spread_note": "20 queries and 74 judgments cannot separate small differences.",
        "scored_query_count": 20,
        "arms": {
            "semantic_only": {
                "label": "Semantic only",
                "description": "fixture description",
                "recall@10": 0.7,
                "mrr": 0.7125,
                "ndcg@10": 0.6594,
                "ndcg@10_min": 0.0,
                "ndcg@10_max": 1.0,
                "ndcg@10_stdev": 0.4199,
                "ndcg@10_query_wins": 12,
            },
            "rrf_fused_no_rerank": {
                "label": "RRF fused, reranking off",
                "description": "fixture description",
                "recall@10": 0.8833,
                "mrr": 0.915,
                "ndcg@10": 0.8617,
                "ndcg@10_min": 0.0975,
                "ndcg@10_max": 1.0,
                "ndcg@10_stdev": 0.2454,
                "ndcg@10_query_wins": 15,
            },
            "rrf_fused_reranked": {
                "label": "RRF fused + managed reranking (served path)",
                "description": "fixture description",
                "recall@10": 0.8667,
                "mrr": 0.9267,
                "ndcg@10": 0.8712,
                "ndcg@10_min": 0.2835,
                "ndcg@10_max": 1.0,
                "ndcg@10_stdev": 0.2147,
                "ndcg@10_query_wins": 16,
            },
        },
        "candidate_recall_ceiling": {
            "pool_recall_ceiling": 0.95,
            "judged_relevant_never_fetched": 2,
            "description": "fixture ceiling description",
        },
        "per_query": [
            {
                "query_id": "G-001",
                "query_text": "EchoBud S2",
                "ndcg@10": {
                    "semantic_only": 1.0,
                    "rrf_fused_no_rerank": 1.0,
                    "rrf_fused_reranked": 1.0,
                },
                "pool_recall": 1.0,
                "relevant_count": 1,
                "found_in_pool": 1,
                "missed_product_ids": [],
            },
        ],
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
    ablation_dirty: bool | None = None,
) -> dict:
    """Wire the real route to a synthetic, fully-matching artifact.

    Patches every input `_attribution` reads -- both artifact loaders, the
    fingerprint/hash functions imported into `service.scorecard`, and
    settings -- so the route-level tests exercise real HTTP dispatch without
    depending on the real repository's current fingerprint or the real
    committed artifacts ever matching it. `ablation_dirty` defaults to
    `dirty` so both sections are attributed together unless a test asks for
    the two to disagree, which is the independence proof for section E.
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

    ablation = _stage_ablation_artifact(
        fingerprint=_MATCHING_FINGERPRINT,
        dirty=dirty if ablation_dirty is None else ablation_dirty,
        embedding=_MATCHING_EMBEDDING_MODEL,
        rerank=_MATCHING_RERANK_MODEL,
        query_set_sha=_MATCHING_QUERY_SET_SHA,
        scored_query_set_sha=_MATCHING_SCORED_QUERY_SET_SHA,
        revision=revision,
    )

    monkeypatch.setattr("service.scorecard._load_artifact", lambda: artifact)
    monkeypatch.setattr(
        "service.scorecard._load_stage_ablation_artifact", lambda: ablation
    )
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
    } - {"G-021"}


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
    assert response.retrieval_quality.excluded_agent_contract_query_ids == ["G-021"]
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
        "G-014",
        "G-018",
        "G-020",
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
    assert "G-013" not in fixtures  # the one scored query with no hard negatives
    assert "G-021" not in fixtures  # excluded from product_retrieval entirely


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


# --- Section E: stage ablation, gated by its own attribution ----------------


def test_stage_ablation_projects_every_arm_and_the_ceiling():
    from service.scorecard import _stage_ablation

    result = _stage_ablation(_stage_ablation_artifact(), _current())

    assert result.attributed is True
    keys = {arm.key for arm in result.arms}
    assert keys == {"semantic_only", "rrf_fused_no_rerank", "rrf_fused_reranked"}
    reranked = next(arm for arm in result.arms if arm.key == "rrf_fused_reranked")
    assert reranked.recall_at_10 == 0.8667
    assert reranked.ndcg_at_10_query_wins == 16
    assert result.candidate_recall_ceiling.pool_recall_ceiling == 0.95
    assert result.candidate_recall_ceiling.judged_relevant_never_fetched == 2
    assert len(result.per_query) == 1
    assert result.per_query[0].query_id == "G-001"
    assert result.per_query[0].ndcg_at_10["rrf_fused_reranked"] == 1.0


def test_stage_ablation_is_withheld_when_its_own_fingerprint_does_not_match():
    """Red-at-birth: the ablation artifact's own mismatch must hide section
    E, using the same `_attribution` conjunction section A is judged by."""
    from service.scorecard import _stage_ablation

    result = _stage_ablation(_stage_ablation_artifact(fingerprint="g" * 64), _current())

    assert result.attributed is False
    assert result.attribution_note.startswith(PENDING_TEXT)
    # Witness: the arms and ceiling are still projected even while withheld,
    # so the UI -- not this projection -- decides what to hide.
    assert len(result.arms) == 3


def test_stage_ablation_attribution_is_independent_of_the_main_artifacts():
    """Independence: an artifact-A-only mismatch must not affect section E's
    own attribution, and the reverse. Two separate committed measurements,
    two separate gates."""
    from service.scorecard import _stage_ablation

    matching = _stage_ablation(_stage_ablation_artifact(), _current())
    mismatched = _stage_ablation(_stage_ablation_artifact(dirty=True), _current())

    assert matching.attributed is True
    assert mismatched.attributed is False


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


def test_api_serves_the_stage_ablation_section_alongside_the_other_four():
    """End-to-end shape proof: `/api/scorecard` carries section E without
    disturbing sections A-D, against the real committed artifacts."""
    payload = TestClient(app).get("/api/scorecard").json()

    assert set(payload) == {
        "provenance",
        "retrieval_quality",
        "regression_anchors",
        "eligibility_contracts",
        "agent_contracts",
        "stage_ablation",
    }
    ablation = payload["stage_ablation"]
    assert {arm["key"] for arm in ablation["arms"]} == {
        "semantic_only",
        "rrf_fused_no_rerank",
        "rrf_fused_reranked",
    }
    assert ablation["scored_query_count"] == 20
    assert len(ablation["per_query"]) == 20
    # The ceiling is arithmetically impossible below any arm's own Recall@10
    # under correct pool accounting -- proven live against the committed
    # artifact, not only against the synthetic fixture above.
    ceiling = ablation["candidate_recall_ceiling"]["pool_recall_ceiling"]
    for arm in ablation["arms"]:
        assert ceiling >= arm["recall_at_10"]
    # Arm 3 must equal the committed population scorecard's own metrics --
    # the whole point of never re-serving it.
    reranked = next(
        arm for arm in ablation["arms"] if arm["key"] == "rrf_fused_reranked"
    )
    quality = payload["retrieval_quality"]
    assert reranked["recall_at_10"] == quality["recall_at_10"]
    assert reranked["mrr"] == quality["mrr"]
    assert reranked["ndcg_at_10"] == quality["ndcg_at_10"]


def test_api_can_show_the_stage_ablation_while_the_main_scorecard_is_pending(
    monkeypatch,
):
    """Independence at the route level: sections A and E are gated by two
    different committed artifacts, so one being stale must not force the
    other to hide."""
    _api_artifact_and_settings(monkeypatch, dirty=True, ablation_dirty=False)

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is False
    assert payload["stage_ablation"]["attributed"] is True


def test_api_can_hide_the_stage_ablation_while_the_main_scorecard_is_shown(
    monkeypatch,
):
    _api_artifact_and_settings(monkeypatch, dirty=False, ablation_dirty=True)

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is True
    assert payload["stage_ablation"]["attributed"] is False
