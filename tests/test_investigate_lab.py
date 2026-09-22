"""Falsifiers for the participant's paired-run and citation challenges."""

from copy import deepcopy

import pytest

from scripts.investigate_lab import citation_challenges, paired_searches
from scripts.validate_lab import LabValidationError


def pair():
    run = {
        "search_event_id": "before",
        "query_text": "monitor",
        "filters": {},
        "dataset_manifest_sha256": "catalog",
        "retrieval_profile": {"rrf_k": 60},
        "embedding_model_id": "embedding-model",
        "rerank_model_id": "rerank-model",
        "retrieval_strategy": "hybrid",
    }
    before = {"run": run, "candidates": [{"product_id": 1}]}
    after = {
        "run": {**run, "search_event_id": "after"},
        "candidates": [
            {"product_id": 2, "fused_rank": 24, "result_rank": 2, "eligible": True}
        ],
    }
    return before, after, {"query": "monitor", "filters": {}, "target_product_ids": [2]}


def test_full_pool_recovery_positive_control():
    report = paired_searches(*pair())
    assert report["after_in_pool"] and not report["before_in_pool"]
    assert report["final_position"] == 2


def test_missing_catalog_selection_stops_before_http_or_database(monkeypatch, tmp_path):
    from scripts import investigate_lab

    response = tmp_path / "response.json"
    response.write_text('{"search_event_id":"event"}')
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args: None)
    monkeypatch.setattr("service.catalog_runtime.active_dataset", lambda: None)
    monkeypatch.setattr(
        investigate_lab,
        "_request",
        lambda *args: pytest.fail("HTTP called before dataset check"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "investigate_lab",
            "arms",
            "--response",
            str(response),
            "--output",
            str(tmp_path / "report.json"),
        ],
    )
    with pytest.raises(LabValidationError, match="export MOSAIC_CATALOG_DATASET"):
        investigate_lab.main()


@pytest.mark.parametrize(
    "field",
    [
        "query_text",
        "filters",
        "dataset_manifest_sha256",
        "retrieval_profile",
        "embedding_model_id",
        "rerank_model_id",
        "retrieval_strategy",
    ],
)
def test_changed_question_settings_or_dataset_cannot_prove_repair(field):
    before, after, mission = pair()
    after["run"][field] = "different"
    with pytest.raises(LabValidationError, match=field):
        paired_searches(before, after, mission)


@pytest.mark.parametrize(
    "failure", ["empty_before", "already_present", "missing_after", "ineligible_after"]
)
def test_recovery_requires_a_real_failed_pool_and_eligible_recovery(failure):
    before, after, mission = pair()
    if failure == "empty_before":
        before["candidates"] = []
    elif failure == "already_present":
        before["candidates"].append({"product_id": 2})
    elif failure == "missing_after":
        after["candidates"] = []
    else:
        after["candidates"][0]["eligible"] = False
    with pytest.raises(LabValidationError):
        paired_searches(before, after, mission)


def citations():
    products = [
        {
            "product_id": i,
            "sku": f"SKU-{i}",
            "title": title,
            "short_description": "Source product",
            "domain": "home_office",
            "category_key": "chair",
            "category_path": "Chairs",
            "brand": title,
            "model": title,
            "review_count": 0,
            "attributes": {},
            "tags": [],
            "price_cents": None,
            "list_price_cents": None,
            "availability": None,
            "inventory_count": None,
        }
        for i, title in [(1, "Oak Model"), (2, "Pine Model")]
    ]
    records = {
        i: {
            "evidence_id": i,
            "product_id": i,
            "evidence_type": "product_spec",
            "source_name": "Test source",
            "source_uri": f"https://example.invalid/{i}",
            "revision": "one",
            "title": "Specification",
            "text": "Adjustable arms.",
        }
        for i in (1, 2)
    }
    agent = {
        "recommendations": products,
        "citations": [
            {
                "number": i,
                **{k: v for k, v in r.items() if k != "text"},
                "quote": r["text"],
            }
            for i, r in records.items()
        ],
    }
    return agent, records


def test_challenges_accept_original_and_reject_changed_records_without_mutation():
    agent, records = citations()
    before = deepcopy((agent, records))
    report = citation_challenges(agent, records)
    assert len(report["negative_controls"]) == 4
    assert report["positive_control"] == "accepted"
    assert (agent, records) == before


def test_no_positive_control_is_not_a_negative_proof():
    agent, records = citations()
    records[1]["revision"] = "changed"
    with pytest.raises(LabValidationError, match="positive control"):
        citation_challenges(agent, records)


def test_challenge_fails_if_receipt_checker_accepts_anything(monkeypatch):
    monkeypatch.setattr("service.lab_checks._citation_resolves", lambda *args: True)
    with pytest.raises(LabValidationError, match="accepted a mutation"):
        citation_challenges(*citations())


def test_challenge_fails_if_production_product_guard_is_disabled(monkeypatch):
    monkeypatch.setattr(
        "service.synthesis._validate_product_claim_citations", lambda *args: None
    )
    with pytest.raises(LabValidationError, match="accepted the other product"):
        citation_challenges(*citations())
