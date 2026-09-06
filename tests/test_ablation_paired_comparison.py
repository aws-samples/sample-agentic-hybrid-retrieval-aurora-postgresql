"""Each step is compared with the one before it on the same searches.

The arms are not independent samples: every one answers the same scored
queries. Comparing a mean difference against each arm's own per-query standard
deviation -- which is dominated by how much query difficulty varies, and says
nothing about which arm won -- is not a test of anything, and it is the
comparison the shipped caveat used to ask readers to make.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from service.scorecard import _paired_comparisons

ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "evals"
    / ("canonical_stage_ablation.json")
)
FUSED = "rrf_fused_no_rerank"
RERANKED = "rrf_fused_reranked"
SEMANTIC = "semantic_only"


def rows(pairs: list[tuple[float, float, float]]) -> list[dict]:
    return [
        {
            "query_id": f"G-{index:03d}",
            "ndcg@10": {SEMANTIC: semantic, FUSED: fused, RERANKED: reranked},
        }
        for index, (semantic, fused, reranked) in enumerate(pairs, 1)
    ]


def test_a_constant_gain_is_separable_however_hard_the_queries_are():
    """The case the two rules disagree on, which is the whole point.

    Every search improves by exactly the same amount, so the step is as real as
    a measurement can be. Query difficulty still varies enormously, so each
    arm's *own* standard deviation dwarfs the gain -- and the old rule would
    have called a perfectly consistent improvement "within noise".
    """
    per_query = rows(
        [(0.1, 0.4, 0.4), (0.5, 0.8, 0.8), (0.0, 0.3, 0.3), (0.9, 1.0, 1.0)]
    )
    fusion = next(
        step for step in _paired_comparisons(per_query) if step.to_key == FUSED
    )

    per_arm_spread = statistics.stdev([row["ndcg@10"][FUSED] for row in per_query])
    assert fusion.mean_difference < per_arm_spread, (
        "fixture must be one the old per-arm rule would have called noise"
    )
    assert fusion.difference_stdev < fusion.mean_difference
    assert fusion.separable is True
    assert (fusion.wins, fusion.losses) == (4, 0)


def test_a_step_that_helps_some_searches_and_hurts_others_is_not_separable():
    per_query = rows(
        [(0.2, 0.9, 0.9), (0.2, 0.1, 0.1), (0.2, 0.8, 0.8), (0.2, 0.0, 0.0)]
    )
    fusion = next(
        step for step in _paired_comparisons(per_query) if step.to_key == FUSED
    )

    assert fusion.separable is False
    assert fusion.wins == 2
    assert fusion.losses == 2
    assert "cannot tell it apart" in fusion.verdict


def test_every_step_reports_its_own_wins_losses_and_ties():
    """A mean hides the distribution the participant needs to see."""
    per_query = rows([(0.1, 0.5, 0.5), (0.4, 0.4, 0.9), (0.6, 0.2, 0.2)])

    for step in _paired_comparisons(per_query):
        assert step.wins + step.losses + step.ties == len(per_query)
        assert str(step.wins) in step.verdict or step.separable


def test_the_committed_measurement_is_reported_honestly():
    """The shipped numbers, read the right way.

    Neither step clears the bar on 20 queries -- including the combined-search
    step, which is the one the session teaches. That is the finding, and it is
    the reason this comparison is served rather than left to the reader to do
    by subtracting two averages.
    """
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    steps = {step.to_key: step for step in _paired_comparisons(artifact["per_query"])}

    assert set(steps) == {FUSED, RERANKED}
    for step in steps.values():
        assert step.separable is False
        assert step.wins + step.losses + step.ties == artifact["scored_query_count"]
    # Reranking leaves most searches untouched and swings a few hard, which is a
    # far more useful lesson than its average.
    assert steps[RERANKED].ties > steps[RERANKED].wins + steps[RERANKED].losses


def test_the_caveat_no_longer_asks_for_the_wrong_comparison():
    harness = (
        Path(__file__).resolve().parents[1] / "scripts" / "ablation_evals.py"
    ).read_text(encoding="utf-8")

    assert "spread of the differences" in harness
    assert 'smaller than that\n    "spread"' not in harness
