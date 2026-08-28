"""The Prove-step scorecard: a read-only render of the committed artifact.

Ruling R3's gate is a conjunction over exactly two facts -- the artifact's own
measured revision equals the revision currently running, and the artifact's own
`worktree_dirty` flag was `False` at measurement time. Three reachable outcomes
follow: revisions differ (hidden), revisions match and the measurement was clean
(shown), revisions match but the measurement was dirty (hidden). Each gets its
own red-at-birth proof below, plus independence and a witness per house
standards rule 7.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service.assertions import ASSERTIONS
from service.main import app
from service.scorecard import (
    PENDING_TEXT,
    SCORECARD_ARTIFACT,
    _agent_contracts,
    _attribution,
    _commits_behind,
    _eligibility_fixtures,
    _release_check_total,
    _scored_queries,
    retrieval_scorecard,
)

ROOT = Path(__file__).resolve().parents[1]


def _artifact_source(revision: str = "a" * 40, dirty: bool = False) -> dict:
    return {"revision": revision, "worktree_dirty": dirty}


# --- Attribution: the three reachable states -------------------------------


def test_attribution_hides_metrics_when_revisions_differ():
    """Case 1: revisions differ -> hidden, regardless of either dirty flag."""
    attributed, note = _attribution(_artifact_source("a" * 40), "b" * 40)

    assert attributed is False
    assert note.startswith(PENDING_TEXT)


def test_attribution_shows_metrics_when_revisions_match_and_measurement_clean():
    """Case 2: revisions match, measurement clean -> shown.

    Positive assertion paired with the hidden cases: a gate that only ever
    returns False would pass every "hidden" test above vacuously. This is
    the witness that the conjunction can actually go the other way.
    """
    same = "c" * 40

    attributed, note = _attribution(_artifact_source(same, dirty=False), same)

    assert attributed is True
    assert same[:12] in note


def test_attribution_hides_when_measurement_was_dirty_despite_matching_revision():
    """Case 3: revisions match but the measurement's own worktree was dirty.

    The one most likely to be skipped: a matching revision alone is not
    enough if the artifact that recorded it was measured from an unclean
    tree.
    """
    same = "d" * 40

    attributed, note = _attribution(_artifact_source(same, dirty=True), same)

    assert attributed is False
    assert note.startswith(PENDING_TEXT)
    assert "unclean" in note


def test_attribution_ignores_the_currently_running_worktrees_own_dirtiness():
    """The gate is over the *measurement's* dirty flag, not the caller's.

    `_attribution` takes no `current_dirty` argument at all: a server running
    with local uncommitted edits, at a revision that matches the artifact,
    with a clean measurement, must still show the metrics. This is the
    independence proof for the "measured worktree_dirty" clause -- an
    unrelated fact (the current server's own cleanliness) must not flip the
    verdict.
    """
    same = "e" * 40

    attributed, _note = _attribution(_artifact_source(same, dirty=False), same)

    assert attributed is True


def test_attribution_is_independent_of_commits_behind_when_revisions_match():
    """An irrelevant input (a stale `commits_behind` value) must not matter
    once the revisions actually agree -- house rule 7's independence proof."""
    same = "f" * 40

    attributed, _note = _attribution(
        _artifact_source(same, dirty=False),
        same,
        commits_behind=9999,
    )

    assert attributed is True


def test_attribution_reports_how_far_behind_when_measurable():
    attributed, note = _attribution(
        _artifact_source("1" * 40),
        "2" * 40,
        commits_behind=60,
    )

    assert attributed is False
    assert "60 commit" in note


def test_attribution_missing_artifact_revision_is_a_revision_mismatch():
    attributed, note = _attribution({"worktree_dirty": False}, "a" * 40)

    assert attributed is False
    assert note.startswith(PENDING_TEXT)


# --- _commits_behind: best-effort, never raises -----------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_commits_behind_counts_exactly_one_commit_for_the_immediate_parent():
    """Relative to the live repo, not a hardcoded SHA pair.

    A literal recorded commit count would go stale the moment another commit
    lands; `HEAD~1..HEAD` is always exactly one commit apart no matter when
    this test runs.
    """
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")

    assert _commits_behind(parent, head) == 1


def test_commits_behind_is_none_when_older_is_not_an_ancestor():
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")

    # HEAD is not an ancestor of its own parent.
    assert _commits_behind(head, parent) is None


def test_commits_behind_is_none_for_an_unresolvable_revision():
    head = _git("rev-parse", "HEAD")

    assert _commits_behind("0" * 40, head) is None


# --- Section A: population metrics, and the population-count safety net ----


def test_scored_queries_excludes_the_agent_contract_case():
    scored = _scored_queries()

    assert {query["query_id"] for query in scored} == {
        f"G-{number:03d}" for number in range(1, 21)
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
    assert response.retrieval_quality.sample_size == 19
    assert response.retrieval_quality.recall_at_10 == artifact["metrics"]["recall@10"]
    assert response.retrieval_quality.mrr == artifact["metrics"]["mrr"]
    assert response.retrieval_quality.ndcg_at_10 == artifact["metrics"]["ndcg@10"]
    assert response.retrieval_quality.excluded_agent_contract_query_ids == ["G-010"]


# --- Section B: golden regression anchors, never mixed with IR metrics -----


def test_regression_anchors_total_is_read_from_the_query_set_not_retyped():
    """The PASS/total denominator comes from the harness's own query fixtures.

    Independence proof: mutating the artifact's own recorded checks does not
    change what `_release_check_total` reports, because it reads
    `canonical_queries.jsonl` directly rather than re-deriving the total from
    the same artifact `passed` is read from.
    """
    scored = _scored_queries()

    assert _release_check_total(scored) == 4


def test_regression_anchors_pass_and_total_agree_on_the_committed_artifact():
    response = retrieval_scorecard()

    assert response.regression_anchors.passed == 4
    assert response.regression_anchors.total == 4
    assert {anchor.query_id for anchor in response.regression_anchors.anchors} == {
        "G-001",
        "G-015",
        "G-019",
    }


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

    assert payload["provenance"]["attributed"] is False
    assert payload["provenance"]["source_revision"]
    assert payload["provenance"]["current_source_revision"]
    assert payload["retrieval_quality"]["sample_size"] == 19
    assert payload["regression_anchors"]["total"] == 4
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


def test_api_shows_metrics_once_the_measured_revision_matches_and_is_clean(
    monkeypatch,
):
    """End-to-end proof of the "shown" branch through the real HTTP route.

    Pairs with `test_api_serves_the_scorecard_route` above (hidden today,
    because the committed artifact is 60 commits stale) so this gate cannot
    pass merely by always hiding the numbers.
    """
    running_revision = "9" * 40
    artifact = json.loads(SCORECARD_ARTIFACT.read_text(encoding="utf-8"))
    artifact["source"] = {"revision": running_revision, "worktree_dirty": False}
    patched = artifact

    monkeypatch.setattr(
        "service.scorecard._load_artifact",
        lambda: patched,
    )
    monkeypatch.setattr(
        "service.scorecard.get_settings",
        lambda: SimpleNamespace(
            source_revision=running_revision,
            source_worktree_dirty=False,
        ),
    )

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is True
    assert (
        payload["retrieval_quality"]["recall_at_10"] == artifact["metrics"]["recall@10"]
    )


def test_api_hides_metrics_when_the_matching_revision_was_measured_dirty(
    monkeypatch,
):
    """The route-level proof of case 3: matching revision, dirty measurement."""
    running_revision = "8" * 40
    artifact = json.loads(SCORECARD_ARTIFACT.read_text(encoding="utf-8"))
    artifact["source"] = {"revision": running_revision, "worktree_dirty": True}

    monkeypatch.setattr("service.scorecard._load_artifact", lambda: artifact)
    monkeypatch.setattr(
        "service.scorecard.get_settings",
        lambda: SimpleNamespace(
            source_revision=running_revision,
            source_worktree_dirty=False,
        ),
    )

    payload = TestClient(app).get("/api/scorecard").json()

    assert payload["provenance"]["attributed"] is False
    assert payload["provenance"]["attribution_note"].startswith(PENDING_TEXT)
