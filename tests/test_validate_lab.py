import pytest

from scripts import validate_lab


def _agent_response():
    recommendations = [
        {
            "product_id": product_id,
            "domain": "home_office",
            "price_cents": price,
            "availability": "in_stock",
            "attributes": {},
        }
        for product_id, price in ((370001, 69900), (429001, 16999))
    ]
    return {
        "recommendations": recommendations,
        "trace": [
            {
                "tool": "search_products",
                "outcome": "success",
                "origin": "model",
                "retrieval_run_id": "run-1",
                "arguments": {
                    "applied_filters": {
                        "domain": "home_office",
                        "max_price_cents": 80000,
                        "in_stock_only": True,
                    }
                },
            },
            {
                "tool": "compare_products",
                "outcome": "success",
                "origin": "model",
                "arguments": {"product_ids": [370001, 429001]},
            },
            {
                "tool": "get_product_evidence",
                "outcome": "success",
                "origin": "model",
                "result_count": 2,
                "arguments": {"product_id": 370001},
            },
            {
                "tool": "get_product_evidence",
                "outcome": "success",
                "origin": "model",
                "result_count": 2,
                "arguments": {"product_id": 429001},
            },
            {
                "tool": "explain_retrieval",
                "outcome": "success",
                "origin": "model",
                "result_count": 2,
                "arguments": {"product_ids": [370001, 429001]},
            },
        ],
        "citations": [
            {
                "number": 1,
                "evidence_id": 9001,
                "evidence_type": "product_spec",
                "product_id": 370001,
                "source_uri": "mosaic://evidence/9001",
                "revision": "2026-08-11",
                "quote": "Supports 12-hour workdays.",
            },
            {
                "number": 2,
                "evidence_id": 9002,
                "evidence_type": "product_spec",
                "product_id": 429001,
                "source_uri": "mosaic://evidence/9002",
                "revision": "2026-08-11",
                "quote": "Damped tactile switches reduce typing noise.",
            },
        ],
    }


def _mission():
    return {
        "filters": {
            "domain": "home_office",
            "max_price_cents": 80000,
            "in_stock_only": True,
        },
        "target_product_ids": [370001, 429001],
        "required_citation_support": [
            {
                "product_id": 370001,
                "evidence_type": "product_spec",
                "all_terms": ["12", "hour"],
            }
        ],
    }


def _fake_request(_base_url, path, _payload=None):
    if path.startswith("/api/retrieval/events/"):
        return {
            "candidates": [
                {
                    "product_id": product_id,
                    "fused_rank": rank,
                    "rerank_rank": rank,
                    "result_rank": rank,
                }
                for rank, product_id in enumerate((370001, 429001), 1)
            ]
        }
    evidence_id = int(path.rsplit("/", 1)[-1])
    citation = next(
        item
        for item in _agent_response()["citations"]
        if item["evidence_id"] == evidence_id
    )
    return {
        "evidence_id": evidence_id,
        "product_id": citation["product_id"],
        "source_uri": citation["source_uri"],
        "revision": citation["revision"],
        "text": citation["quote"],
    }


def test_lab_3_validator_proves_tools_grounding_and_citations(monkeypatch):
    monkeypatch.setattr(validate_lab, "_request", _fake_request)

    checks = validate_lab.validate_agent_response(
        "http://example.test",
        _mission(),
        _agent_response(),
    )

    assert "citation IDs resolve exactly" in checks
    assert "required claims supported" in checks
    assert "tool execution origins explicit" in checks


def test_lab_3_validator_rejects_an_unattributed_controller_step(monkeypatch):
    monkeypatch.setattr(validate_lab, "_request", _fake_request)
    response = _agent_response()
    response["trace"][0].pop("origin")

    with pytest.raises(validate_lab.LabValidationError, match="execution origin"):
        validate_lab.validate_agent_response(
            "http://example.test",
            _mission(),
            response,
        )


def test_lab_3_validator_rejects_unresolved_citation(monkeypatch):
    def mismatched(base_url, path, payload=None):
        result = _fake_request(base_url, path, payload)
        if path.startswith("/api/evidence/"):
            result["product_id"] = 123
        return result

    monkeypatch.setattr(validate_lab, "_request", mismatched)

    with pytest.raises(validate_lab.LabValidationError, match="does not resolve"):
        validate_lab.validate_agent_response(
            "http://example.test",
            _mission(),
            _agent_response(),
        )


def test_lab_3_validator_requires_citation_coverage(monkeypatch):
    monkeypatch.setattr(validate_lab, "_request", _fake_request)
    response = _agent_response()
    response["citations"] = response["citations"][:1]

    with pytest.raises(validate_lab.LabValidationError, match="every recommended"):
        validate_lab.validate_agent_response(
            "http://example.test",
            _mission(),
            response,
        )


def test_lab_3_validator_requires_one_successful_ranking_explanation(monkeypatch):
    monkeypatch.setattr(validate_lab, "_request", _fake_request)
    response = _agent_response()
    response["trace"] = [
        step for step in response["trace"] if step["tool"] != "explain_retrieval"
    ]

    with pytest.raises(
        validate_lab.LabValidationError,
        match="exactly one successful explain_retrieval",
    ):
        validate_lab.validate_agent_response(
            "http://example.test",
            _mission(),
            response,
        )


def test_lab_3_validator_rejects_a_resolved_but_unsupported_claim(monkeypatch):
    response = _agent_response()
    response["citations"][0]["quote"] = "Supports extended workdays."

    def unsupported(_base_url, path, _payload=None):
        if path.startswith("/api/retrieval/events/"):
            return _fake_request(_base_url, path, _payload)
        evidence_id = int(path.rsplit("/", 1)[-1])
        citation = next(
            item for item in response["citations"] if item["evidence_id"] == evidence_id
        )
        return {
            "evidence_id": evidence_id,
            "product_id": citation["product_id"],
            "source_uri": citation["source_uri"],
            "revision": citation["revision"],
            "text": citation["quote"],
        }

    monkeypatch.setattr(validate_lab, "_request", unsupported)

    with pytest.raises(
        validate_lab.LabValidationError,
        match="required citation support.*12.*hour",
    ):
        validate_lab.validate_agent_response(
            "http://example.test",
            _mission(),
            response,
        )


def test_lab_3_validator_rejects_dropped_jsonb_constraints(monkeypatch):
    monkeypatch.setattr(validate_lab, "_request", _fake_request)
    mission = _mission()
    mission["filters"]["attributes"] = {"seat_depth_adjustable": True}

    with pytest.raises(
        validate_lab.LabValidationError,
        match="does not preserve structured constraints",
    ):
        validate_lab.validate_agent_response(
            "http://example.test",
            mission,
            _agent_response(),
        )


def _lab_2_response(*, pre_rerank_rank=1, final_rank=1):
    rrf_k = 60
    contribution = 1 / (rrf_k + 1)
    return {
        "results": [
            {
                "product_id": 370002,
                "signals": {
                    arm: {
                        "rank": 1,
                        "rrf_contribution": contribution,
                    }
                    for arm in ("fts", "trigram", "semantic")
                }
                | {
                    "rrf_score": contribution * 3,
                    "pre_rerank_rank": pre_rerank_rank,
                    "rerank_score": 0.93,
                    "final_rank": final_rank,
                },
            }
        ],
        "diagnostics": {
            "retrieval_profile": {"rrf_k": rrf_k},
            "rerank_status": "applied",
        },
    }


def test_lab_2_validator_proves_the_canonical_fused_and_final_winner(monkeypatch):
    response = _lab_2_response()
    monkeypatch.setattr(
        validate_lab,
        "_mission",
        lambda _stage: {"target_product_ids": [370002]},
    )
    monkeypatch.setattr(validate_lab, "_search", lambda _url, _mission: response)

    checks = validate_lab.validate_lab_2("http://example.test")

    assert "canonical winner is fused and final rank 1" in checks


def test_lab_2_validator_rejects_a_wrong_fused_winner(monkeypatch):
    response = _lab_2_response(pre_rerank_rank=2)
    monkeypatch.setattr(
        validate_lab,
        "_mission",
        lambda _stage: {"target_product_ids": [370002]},
    )
    monkeypatch.setattr(validate_lab, "_search", lambda _url, _mission: response)

    with pytest.raises(validate_lab.LabValidationError, match="not fused rank 1"):
        validate_lab.validate_lab_2("http://example.test")
