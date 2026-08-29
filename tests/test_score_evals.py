import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from scripts.score_evals import (
    _scorecard_only_revision_delta,
    _write_ranked_results,
    concept_label,
    label_per_query_metrics,
    measured_scorecard,
    product_retrieval_queries,
    query_set_sha256,
    ranked_result_sha256,
    run_scored_queries,
    search_with_db_retry,
    validate_hard_negatives,
    validate_release_checks,
    verify_scorecard,
)
from service.models import SearchRequest

ROOT = Path(__file__).resolve().parents[1]


class FakeRetrieval:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.queries = []

    def search(self, request):
        self.queries.append(request.query)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def search_response(product_id):
    return SimpleNamespace(
        results=[
            SimpleNamespace(
                product_id=product_id,
                signals=SimpleNamespace(final_rank=1),
            )
        ],
        search_event_id=f"event-{product_id}",
        diagnostics=SimpleNamespace(
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            total_latency_ms=125,
        ),
    )


def scorecard(*, recall=0.8, mrr=0.7, ndcg=0.75):
    return {
        "query_set": "data/evals/canonical_queries.jsonl",
        "query_set_sha256": query_set_sha256(
            ROOT / "data" / "evals" / "canonical_queries.jsonl"
        ),
        "scored_query_set_sha256": "scored-query-set",
        "retrieval_fingerprint": "c" * 64,
        "canonical_query_count": 20,
        "product_retrieval_query_count": 19,
        "excluded_agent_contract_queries": ["G-021"],
        "deterministic_release_checks": [],
        "ranked_result_sha256": "ranked-result-set",
        "k": 10,
        "models": {
            "embedding": "us.cohere.embed-v4:0",
            "rerank": "cohere.rerank-v3-5:0",
        },
        "source": {"revision": "a" * 40, "worktree_dirty": False},
        "dataset_manifest_sha256": "b" * 64,
        "retrieval_profile": {"rrf_k": 60},
        "hnsw_settings": {
            "ef_search": 100,
            "iterative_scan": "relaxed_order",
            "max_scan_tuples": 20000,
            "scan_mem_multiplier": 1,
        },
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "database_version": "18.3",
            "vector_extension_version": "0.8.1",
            "instance_class": "db.r8g.2xlarge",
        },
        "database_instance_id": "workshop-writer",
        "measured_at": "2026-08-15T00:00:00+00:00",
        "strategy": "rrf_fusion+rerank+exact_sku_preservation",
        "metrics": {
            "recall@10": recall,
            "mrr": mrr,
            "ndcg@10": ndcg,
        },
    }


def test_scorecard_accepts_equal_or_improved_measured_metrics():
    baseline = scorecard()
    measured = scorecard(recall=0.85, mrr=0.72, ndcg=0.8)

    verify_scorecard(measured, baseline)


def test_committed_scorecard_keeps_per_query_and_ranked_result_provenance():
    baseline = json.loads(
        (ROOT / "data" / "evals" / "canonical_scorecard.json").read_text()
    )

    assert (
        len(baseline["per_query_metrics"]) == baseline["product_retrieval_query_count"]
    )
    assert {row["query_id"] for row in baseline["per_query_metrics"]} == {
        f"G-{number:03d}" for number in range(1, 22)
    } - {"G-021"}
    assert len(baseline["ranked_result_sha256"]) == 64
    assert len(baseline["dataset_manifest_sha256"]) == 64
    assert baseline["source"]["revision"]
    assert isinstance(baseline["source"]["worktree_dirty"], bool)
    assert baseline["aurora_configuration"]["instance_class"]
    assert baseline["retrieval_profile"]["rrf_k"] > 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_set_sha256", "changed"),
        ("retrieval_fingerprint", "d" * 64),
        ("product_retrieval_query_count", 20),
        ("k", 20),
        ("models", {"embedding": "another-space", "rerank": "rerank"}),
        ("dataset_manifest_sha256", "changed"),
        ("retrieval_profile", {"rrf_k": 1}),
        ("hnsw_settings", {"ef_search": 1}),
        ("aurora_configuration", {"engine": "postgresql"}),
        ("database_instance_id", "different-writer"),
        ("strategy", "weighted_rrf_fusion+rerank+exact_sku_preservation"),
        ("ranked_result_sha256", "changed"),
    ],
)
def test_scorecard_refuses_unreviewed_provenance_drift(field, value):
    baseline = scorecard()
    measured = scorecard()
    measured[field] = value

    with pytest.raises(ValueError, match="drifted"):
        verify_scorecard(measured, baseline)


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("recall@10", 0.79),
        ("mrr", 0.69),
        ("ndcg@10", 0.74),
    ],
)
def test_scorecard_refuses_metric_regressions(metric, value):
    baseline = scorecard()
    measured = scorecard()
    measured["metrics"][metric] = value

    with pytest.raises(ValueError, match=f"regressed for {metric}"):
        verify_scorecard(measured, baseline)


def test_scorecard_requires_source_revision_and_worktree_state():
    baseline = scorecard()
    measured = scorecard()
    measured["source"] = {"revision": "", "worktree_dirty": "unknown"}

    with pytest.raises(ValueError, match="source provenance is incomplete"):
        verify_scorecard(measured, baseline)


def test_scorecard_refuses_a_dirty_measured_source():
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["worktree_dirty"] = True

    with pytest.raises(ValueError, match="source is dirty"):
        verify_scorecard(measured, baseline)


def test_scorecard_refuses_a_dirty_committed_baseline():
    baseline = scorecard()
    baseline["source"]["worktree_dirty"] = True

    with pytest.raises(ValueError, match="baseline was not captured from a clean"):
        verify_scorecard(scorecard(), baseline)


@pytest.mark.parametrize(
    ("revision", "dirty", "message"),
    [
        ("a" * 40, True, "clean committed source"),
        ("a7ddc1b", False, "full 40-character Git SHA"),
    ],
)
def test_scorecard_rejects_invalid_source_before_aurora_work(
    monkeypatch,
    tmp_path,
    revision,
    dirty,
    message,
):
    monkeypatch.setattr(
        "scripts.score_evals.get_settings",
        lambda: SimpleNamespace(
            source_revision=revision,
            source_worktree_dirty=dirty,
        ),
    )
    monkeypatch.setattr(
        "scripts.score_evals.connect",
        lambda: pytest.fail("Aurora should not be queried before source validation"),
    )

    with pytest.raises(ValueError, match=message):
        measured_scorecard(
            ROOT / "data" / "evals" / "canonical_queries.jsonl",
            tmp_path / "results.csv",
            k=10,
        )


def test_scorecard_requires_instance_class_before_aurora_work(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        "scripts.score_evals.get_settings",
        lambda: SimpleNamespace(
            source_revision="a" * 40,
            source_worktree_dirty=False,
            aurora_instance_class=None,
        ),
    )
    monkeypatch.setattr(
        "scripts.score_evals.connect",
        lambda: pytest.fail(
            "Aurora should not be queried before provenance validation"
        ),
    )

    with pytest.raises(ValueError, match="AURORA_INSTANCE_CLASS"):
        measured_scorecard(
            ROOT / "data" / "evals" / "canonical_queries.jsonl",
            tmp_path / "results.csv",
            k=10,
        )


def test_ranked_results_use_lf_line_endings(tmp_path):
    output = tmp_path / "ranked.csv"

    _write_ranked_results(
        output,
        [{"query_id": "G-001"}],
        {"G-001": [{"query_id": "G-001", "product_id": 2, "rank": 1}]},
    )

    assert output.read_bytes() == (b"query_id,product_id,rank\nG-001,2,1\n")


def test_scorecard_accepts_only_generated_release_artifacts_after_measurement(
    monkeypatch,
    tmp_path,
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "scorecard-test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Scorecard Test"],
        cwd=tmp_path,
        check=True,
    )
    source = tmp_path / "service" / "retrieval.py"
    source.parent.mkdir()
    source.write_text("SOURCE = 'measured'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "measured source"], cwd=tmp_path, check=True
    )
    baseline_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
    ).strip()

    generated = (
        "data/evals/canonical_scorecard.json",
        "data/evals/canonical_ranked_results.csv",
        "data/evals/canonical_stage_ablation.json",
    )
    for relative_path in generated:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative_path}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "record generated artifacts"],
        cwd=tmp_path,
        check=True,
    )
    measured_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
    ).strip()
    monkeypatch.setattr("scripts.score_evals.REPO", tmp_path)

    assert _scorecard_only_revision_delta(baseline_revision, measured_revision)

    source.write_text("SOURCE = 'changed after measurement'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "intervening source change"],
        cwd=tmp_path,
        check=True,
    )
    code_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
    ).strip()

    assert not _scorecard_only_revision_delta(baseline_revision, code_revision)


def test_scorecard_refuses_a_baseline_with_intervening_code_changes(monkeypatch):
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["revision"] = "c" * 40
    monkeypatch.setattr(
        "scripts.score_evals._scorecard_only_revision_delta",
        lambda baseline_revision, measured_revision: False,
    )

    with pytest.raises(ValueError, match="source revision drifted"):
        verify_scorecard(measured, baseline)


def test_scorecard_accepts_the_commit_that_only_records_the_baseline(monkeypatch):
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["revision"] = "c" * 40
    monkeypatch.setattr(
        "scripts.score_evals._scorecard_only_revision_delta",
        lambda baseline_revision, measured_revision: True,
    )

    verify_scorecard(measured, baseline)


def test_scorecard_retries_only_a_transient_database_failure():
    retrieval = FakeRetrieval(
        [psycopg.OperationalError("connection reset by peer"), search_response(101)]
    )
    delays = []

    response = search_with_db_retry(
        retrieval,
        SearchRequest(query="travel headphones", limit=10),
        query_id="G-001",
        retry_delays=(0.25,),
        sleep=delays.append,
    )

    assert response.search_event_id == "event-101"
    assert retrieval.queries == ["travel headphones", "travel headphones"]
    assert delays == [0.25]


def test_scorecard_does_not_retry_a_non_database_failure():
    retrieval = FakeRetrieval([RuntimeError("reranker contract failed")])

    with pytest.raises(RuntimeError, match="reranker contract failed"):
        search_with_db_retry(
            retrieval,
            SearchRequest(query="travel headphones", limit=10),
            query_id="G-001",
            retry_delays=(0.25,),
            sleep=lambda _: None,
        )

    assert retrieval.queries == ["travel headphones"]


def test_scorecard_resumes_completed_queries_after_an_interruption(tmp_path):
    queries = [
        {"query_id": "G-001", "query": "travel headphones"},
        {"query_id": "G-002", "query": "office headphones"},
    ]
    checkpoint = tmp_path / "scorecard.checkpoint.json"
    identity = {"source": {"revision": "a" * 40}, "database": "writer"}
    interrupted = FakeRetrieval(
        [search_response(101), RuntimeError("model service unavailable")]
    )

    with pytest.raises(RuntimeError, match="model service unavailable"):
        run_scored_queries(
            queries,
            interrupted,
            k=10,
            checkpoint_path=checkpoint,
            checkpoint_identity=identity,
            retry_delays=(),
            sleep=lambda _: None,
        )

    resumed = FakeRetrieval([search_response(102)])
    ranked, rows = run_scored_queries(
        queries,
        resumed,
        k=10,
        checkpoint_path=checkpoint,
        checkpoint_identity=identity,
        retry_delays=(),
        sleep=lambda _: None,
    )

    assert resumed.queries == ["office headphones"]
    assert ranked == {"G-001": [(1, 101)], "G-002": [(1, 102)]}
    assert rows["G-001"][0]["search_event_id"] == "event-101"
    assert rows["G-002"][0]["search_event_id"] == "event-102"


def test_scorecard_refuses_a_checkpoint_from_another_run_contract(tmp_path):
    queries = [{"query_id": "G-001", "query": "travel headphones"}]
    checkpoint = tmp_path / "scorecard.checkpoint.json"
    run_scored_queries(
        queries,
        FakeRetrieval([search_response(101)]),
        k=10,
        checkpoint_path=checkpoint,
        checkpoint_identity={"source": {"revision": "a" * 40}},
        retry_delays=(),
        sleep=lambda _: None,
    )

    with pytest.raises(ValueError, match="provenance drifted.*--restart"):
        run_scored_queries(
            queries,
            FakeRetrieval([]),
            k=10,
            checkpoint_path=checkpoint,
            checkpoint_identity={"source": {"revision": "b" * 40}},
            retry_delays=(),
            sleep=lambda _: None,
        )


def test_product_retrieval_scorecard_excludes_agent_contract_cases():
    queries = [
        {"query_id": "G-001"},
        {"query_id": "G-021", "evaluation_scope": "agent_contract"},
    ]

    scored, excluded = product_retrieval_queries(queries)

    assert [query["query_id"] for query in scored] == ["G-001"]
    assert excluded == ["G-021"]


def test_ranked_result_identity_is_stable_but_order_sensitive():
    first = {
        "G-002": [(2, 22), (1, 21)],
        "G-001": [(1, 11), (2, 12)],
    }
    same = {
        "G-001": [(2, 12), (1, 11)],
        "G-002": [(1, 21), (2, 22)],
    }
    changed = {
        "G-001": [(1, 12), (2, 11)],
        "G-002": [(1, 21), (2, 22)],
    }

    assert ranked_result_sha256(first) == ranked_result_sha256(same)
    assert ranked_result_sha256(first) != ranked_result_sha256(changed)


def test_scorecard_rejects_an_unknown_scope_with_a_fix():
    with pytest.raises(ValueError, match="Fix the canonical evaluation scope"):
        product_retrieval_queries(
            [{"query_id": "G-999", "evaluation_scope": "unbounded"}]
        )


@pytest.mark.parametrize(
    ("teaching_concept", "expected"),
    [
        ("exact_identity", "Exact identity"),
        ("semantic_intent_and_filters", "Semantic intent and filters"),
        ("typo_recovery", "Typo recovery"),
        ("multi_attribute_filter", "Multi attribute filter"),
        # Acronyms keep their conventional casing. Without this, these render as
        # "Rrf and reranking", "Jsonb and price filters" and "Eligibility before
        # ann" -- the last reading as a person's name. These labels exist to make
        # internal identifiers legible, so three of them looking like typos
        # defeats the purpose. Every acronym the current query set uses is listed
        # here, so adding a concept with an unlisted acronym fails loudly.
        ("rrf_and_reranking", "RRF and reranking"),
        ("jsonb_and_price_filters", "JSONB and price filters"),
        ("eligibility_before_ann", "Eligibility before ANN"),
        # A slug with no acronym is still purely mechanical.
        ("graded_sibling_ordering", "Graded sibling ordering"),
    ],
)
def test_concept_label_capitalizes_words_and_preserves_acronyms(
    teaching_concept, expected
):
    assert concept_label(teaching_concept) == expected


def test_label_per_query_metrics_puts_query_text_first_and_id_second():
    """Witness: every row in `per_query` gets its own matching query, proven
    by checking the exact set of query_ids labeled, not merely a count that
    could collapse to zero alongside an empty input."""
    per_query = [
        {"query_id": "G-002", "recall@10": 1.0, "reciprocal_rank": 1.0, "ndcg@10": 1.0},
        {"query_id": "G-004", "recall@10": 0.5, "reciprocal_rank": 0.5, "ndcg@10": 0.6},
    ]
    queries = [
        {
            "query_id": "G-002",
            "query": "Sonora WH-C720",
            "teaching_concept": "exact_model_alias",
        },
        {
            "query_id": "G-004",
            "query": "travel ANC headphones",
            "teaching_concept": "semantic_intent_and_filters",
        },
        {"query_id": "G-999", "query": "unused", "teaching_concept": "unused_concept"},
    ]

    labeled = label_per_query_metrics(per_query, queries)

    assert {row["query_id"] for row in labeled} == {"G-002", "G-004"}
    by_id = {row["query_id"]: row for row in labeled}
    assert by_id["G-002"]["query_text"] == "Sonora WH-C720"
    assert by_id["G-002"]["concept_label"] == "Exact model alias"
    assert by_id["G-004"]["query_text"] == "travel ANC headphones"
    assert by_id["G-004"]["concept_label"] == "Semantic intent and filters"
    # The original metric fields survive untouched alongside the new labels.
    assert by_id["G-002"]["recall@10"] == 1.0
    assert by_id["G-004"]["ndcg@10"] == 0.6


def test_release_checks_include_query_text_and_concept_label_when_present():
    checks = validate_release_checks(
        [
            {
                "query_id": "G-001",
                "query": "Sonora WH-C720 headphones",
                "teaching_concept": "exact_identity",
                "release_checks": [{"type": "top_rank", "product_id": 17001}],
            }
        ],
        {"G-001": [(1, 17001)]},
    )

    assert checks == [
        {
            "query_id": "G-001",
            "type": "top_rank",
            "product_id": 17001,
            "query_text": "Sonora WH-C720 headphones",
            "concept_label": "Exact identity",
        }
    ]


def test_release_checks_prove_top_rank_and_top_k_membership():
    checks = validate_release_checks(
        [
            {
                "query_id": "G-001",
                "release_checks": [
                    {"type": "top_rank", "product_id": 17001},
                    {"type": "present_top_k", "product_id": 17002, "k": 2},
                ],
            }
        ],
        {"G-001": [(1, 17001), (2, 17002)]},
    )

    assert checks == [
        {"query_id": "G-001", "type": "top_rank", "product_id": 17001},
        {
            "query_id": "G-001",
            "type": "present_top_k",
            "product_id": 17002,
            "k": 2,
        },
    ]


def test_release_checks_fail_with_observed_results_and_a_fix():
    with pytest.raises(
        ValueError,
        match="requires product 17001 at final rank 1.*Fix the retrieval",
    ):
        validate_release_checks(
            [
                {
                    "query_id": "G-001",
                    "release_checks": [{"type": "top_rank", "product_id": 17001}],
                }
            ],
            {"G-001": [(1, 17002), (2, 17001)]},
        )


def test_hard_negatives_must_stay_out_of_the_result_window():
    """`docs/lab-golden-queries.md` calls these validator-owned controls.

    Before this gate existed, nothing asserted the behaviour: the canonical-eval test
    checks that the fixture grades a hard negative 0, and validate_lab.py checks
    eligibility against the mission filters, which is a different claim — a hard
    negative can satisfy every filter and still be the wrong product.
    """
    queries = [
        {
            "query_id": "G-012",
            "hard_negative_ids": [234001, 210001],
            "judgments": [{"product_id": 234002, "grade": 3, "rationale": "x" * 20}],
        }
    ]
    clean = {"G-012": [(1, 234002), (2, 234003)]}
    validate_hard_negatives(queries, clean)

    leaked = {"G-012": [(1, 234002), (2, 210001)]}
    with pytest.raises(ValueError) as failure:
        validate_hard_negatives(queries, leaked)
    assert "210001" in str(failure.value)
    assert "rank(s) [2]" in str(failure.value)


def test_hard_negative_gate_ignores_a_query_that_declares_none():
    validate_hard_negatives(
        [{"query_id": "G-999", "hard_negative_ids": []}], {"G-999": [(1, 1)]}
    )
