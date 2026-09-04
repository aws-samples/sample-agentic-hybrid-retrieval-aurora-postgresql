"""The lab acceptance checks, evaluated directly on already-loaded evidence.

These are the same functions `scripts/validate_lab.py` and
`service/lab_proof.py` call, so a check that passes here is the check both
transports run. `tests/test_validate_lab.py` covers the HTTP transport's
failure messages; this file covers the check vocabulary itself.
"""

from __future__ import annotations

import pytest

from service import lab_checks
from service.lab_checks import (
    AgentEvidence,
    LabCheck,
    PersistedAgentRun,
    RetrievalReceipt,
)

LAB_1_MISSION = {
    "target_product_ids": [2],
    "filters": {
        "domain": "consumer_electronics",
        "max_price_cents": 20000,
        "in_stock_only": True,
    },
}

LAB_3_MISSION = {
    "target_product_ids": [370001, 429001],
    "filters": {
        "domain": "home_office",
        "max_price_cents": 80000,
        "in_stock_only": True,
    },
}


def _lab_1_response(
    *,
    with_target: bool = True,
    trigram_rank: int | None = 1,
    trigram_contribution: float | None = 0.0164,
    trigram_in_pool: int = 7,
    price_cents: int = 15900,
):
    results = []
    if with_target:
        results.append(
            {
                "product_id": 2,
                "domain": "consumer_electronics",
                "price_cents": price_cents,
                "availability": "in_stock",
                "attributes": {},
                "signals": {
                    "fts": {"rank": None, "rrf_contribution": None},
                    "trigram": {
                        "rank": trigram_rank,
                        "rrf_contribution": trigram_contribution,
                    },
                    "semantic": {"rank": None, "rrf_contribution": None},
                },
            }
        )
    return {
        "results": results,
        "diagnostics": {"candidate_counts": {"trigram_in_pool": trigram_in_pool}},
    }


def _lab_2_response(*, pre_rerank_rank=1, final_rank=1, rerank_status="applied"):
    rrf_k = 60
    contribution = 1 / (rrf_k + 1)
    return {
        "results": [
            {
                "product_id": 370002,
                "signals": {
                    arm: {"rank": 1, "rrf_contribution": contribution}
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
            "rerank_status": rerank_status,
        },
    }


#: `(number, evidence_id, product_id, quote)` for the persisted citations the
#: Lab 3 proof fixtures grade. The quote is carried because the citation check
#: compares it against the evidence row's own text, not only the product id.
_CITED_ROWS = (
    (1, 9001, 370001, "Seat depth adjusts across a 60 mm range."),
    (2, 9002, 429001, "Damped tactile switches cut typing noise."),
)
_REVISION = "2026-08-11"


def _citation(number: int, evidence_id: int, product_id: int, quote: str) -> dict:
    """One persisted citation, in the shape `AgentCitation.model_dump` writes."""
    return {
        "number": number,
        "evidence_id": evidence_id,
        "evidence_type": "product_spec",
        "product_id": product_id,
        "source_uri": f"mosaic://evidence/{evidence_id}",
        "revision": _REVISION,
        "title": "Specification",
        "quote": quote,
    }


def _evidence_row(evidence_id: int, product_id: int, text: str) -> dict:
    """One resolved evidence record, in the shape `EvidenceRecord` serves."""
    return {
        "evidence_id": evidence_id,
        "product_id": product_id,
        "evidence_type": "product_spec",
        "source_uri": f"mosaic://evidence/{evidence_id}",
        "revision": _REVISION,
        "title": "Specification",
        "text": text,
    }


def _persisted_run(**overrides) -> PersistedAgentRun:
    defaults = {
        "agent_run_id": "5e0c2b9a-1f2d-4c3b-8a7e-0d1c2b3a4f56",
        "assistant_message": "The chair and the keyboard both clear the budget.",
        "selected_products": (370001, 429001),
        "synthesis_outcome": "success",
        "citations": tuple(
            _citation(number, evidence_id, product_id, quote)
            for number, evidence_id, product_id, quote in _CITED_ROWS
        ),
        "resolved_evidence": {
            evidence_id: _evidence_row(evidence_id, product_id, quote)
            for _, evidence_id, product_id, quote in _CITED_ROWS
        },
        "evidence_events": (
            {"product_id": 370001, "outcome": "success", "result_count": 2},
            {"product_id": 429001, "outcome": "success", "result_count": 3},
        ),
        "search_filters": (
            {
                "domain": "home_office",
                "max_price_cents": 80000,
                "in_stock_only": True,
            },
        ),
    }
    return PersistedAgentRun(**(defaults | overrides))


def _names(checks):
    return [check.name for check in checks]


def _by_name(checks, name):
    return next(check for check in checks if check.name == name)


def test_a_check_may_not_be_constructed_without_a_falsifier():
    """House rule 2: a check that cannot state its failure is decoration."""
    with pytest.raises(ValueError, match="falsifier"):
        LabCheck(name="anything", passed=True, falsifier="  ", detail="fine")


def test_lab_1_reports_exactly_four_checks():
    checks = lab_checks.lab_1_checks(LAB_1_MISSION, _lab_1_response())

    assert len(checks) == 4, (
        f"expected exactly 4 Lab 1 checks, found {len(checks)}: {_names(checks)}"
    )
    assert all(check.passed for check in checks), _names(
        [check for check in checks if not check.passed]
    )
    assert all(check.falsifier.strip() for check in checks)


def test_lab_1_fails_when_the_anchor_never_arrives():
    checks = lab_checks.lab_1_checks(
        LAB_1_MISSION, _lab_1_response(with_target=False, trigram_in_pool=0)
    )

    assert not _by_name(checks, "expected retrieval anchor present").passed
    assert not _by_name(checks, "trigram candidate pool non-empty").passed
    assert "2" in _by_name(checks, "expected retrieval anchor present").detail


def test_lab_1_fails_when_the_anchor_carries_no_trigram_provenance():
    checks = lab_checks.lab_1_checks(
        LAB_1_MISSION, _lab_1_response(trigram_rank=None, trigram_contribution=None)
    )

    assert _by_name(checks, "expected retrieval anchor present").passed
    assert not _by_name(checks, "trigram provenance present").passed


def test_lab_1_fails_when_a_returned_product_breaks_the_filters():
    checks = lab_checks.lab_1_checks(LAB_1_MISSION, _lab_1_response(price_cents=29900))

    assert not _by_name(checks, "hard filters hold").passed


def test_lab_2_reports_exactly_five_checks():
    response = _lab_2_response()

    checks = lab_checks.lab_2_checks(
        {"target_product_ids": [370002]}, response, response
    )

    assert len(checks) == 5, (
        f"expected exactly 5 Lab 2 checks, found {len(checks)}: {_names(checks)}"
    )
    assert all(check.passed for check in checks), _names(
        [check for check in checks if not check.passed]
    )
    assert "canonical winner is fused and final rank 1" in _names(checks)


def test_lab_2_fails_on_a_wrong_fused_winner():
    response = _lab_2_response(pre_rerank_rank=2)

    checks = lab_checks.lab_2_checks(
        {"target_product_ids": [370002]}, response, response
    )

    failed = _by_name(checks, "canonical winner is fused and final rank 1")
    assert not failed.passed
    assert "not fused rank 1" in failed.detail


def test_lab_2_fails_when_the_pre_rerank_order_is_not_repeatable():
    first = _lab_2_response()
    second = _lab_2_response()
    second["results"][0]["product_id"] = 370003

    checks = lab_checks.lab_2_checks({"target_product_ids": [370002]}, first, second)

    assert not _by_name(checks, "pre-rerank order repeatable").passed


def test_lab_2_fails_when_reranking_never_ran():
    response = _lab_2_response(rerank_status="unavailable")

    checks = lab_checks.lab_2_checks(
        {"target_product_ids": [370002]}, response, response
    )

    assert not _by_name(checks, "reranking bounded and applied").passed


def test_lab_3_proof_reports_exactly_five_checks():
    checks = lab_checks.lab_3_proof_checks(LAB_3_MISSION, _persisted_run())

    assert len(checks) == 5, (
        f"expected exactly 5 Lab 3 proof checks, found {len(checks)}: {_names(checks)}"
    )
    assert all(check.passed for check in checks), _names(
        [check for check in checks if not check.passed]
    )
    assert all(check.falsifier.strip() for check in checks)


def test_lab_3_proof_without_a_persisted_run_names_stage_03():
    checks = lab_checks.lab_3_proof_checks(LAB_3_MISSION, None)

    assert len(checks) == 5
    assert not any(check.passed for check in checks)
    assert all("Stage 03" in check.detail for check in checks), [
        check.detail for check in checks if "Stage 03" not in check.detail
    ]


def test_lab_3_proof_names_the_submitted_id_or_says_none_was_submitted():
    """The two missing-run cases are different mistakes and read differently."""
    absent = lab_checks.lab_3_proof_checks(LAB_3_MISSION, None)
    unknown = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION, None, requested_run_id="5e0c2b9a-1f2d-4c3b-8a7e-0d1c2b3a4f56"
    )

    assert "no agent_run_id was submitted" in absent[0].detail
    assert "5e0c2b9a-1f2d-4c3b-8a7e-0d1c2b3a4f56" in unknown[0].detail
    assert "was submitted" not in unknown[0].detail
    assert all("Stage 03" in check.detail for check in absent + unknown)


def test_lab_3_proof_fails_an_ungrounded_run():
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            assistant_message=None,
            synthesis_outcome=None,
            citations=(),
            resolved_evidence={},
            selected_products=(),
        ),
    )

    assert not _by_name(checks, "answer of record present").passed
    assert not _by_name(checks, "grounded synthesis produced a product scope").passed
    assert not _by_name(checks, "citation evidence resolves").passed
    assert "Stage 03" in _by_name(checks, "answer of record present").falsifier


def test_lab_3_proof_fails_a_citation_that_resolves_to_another_product():
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            resolved_evidence={
                9001: _evidence_row(9001, 123, _CITED_ROWS[0][3]),
                9002: _evidence_row(9002, 429001, _CITED_ROWS[1][3]),
            }
        ),
    )

    failed = _by_name(checks, "citation evidence resolves")
    assert not failed.passed
    assert "9001" in failed.detail


def test_lab_3_proof_fails_a_citation_whose_quote_the_evidence_row_lacks():
    """The persisted-row check compares all five fields, not only product_id.

    A fabricated quote on the right product is the failure the product-id-only
    comparison could not see: the citation addresses a real evidence row and
    still asserts words that row never carried.
    """
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            resolved_evidence={
                9001: _evidence_row(9001, 370001, "Seat depth is fixed."),
                9002: _evidence_row(9002, 429001, _CITED_ROWS[1][3]),
            }
        ),
    )

    failed = _by_name(checks, "citation evidence resolves")
    assert not failed.passed, failed.detail
    assert "9001" in failed.detail


def test_lab_3_proof_reports_a_citation_without_an_evidence_id_as_unresolved():
    """A truncated persisted citation is a failed check, never a 500.

    The proof route grades whatever the ledger holds. A citation row that lost
    its `evidence_id` must be reported as unresolved by name, not raise a
    KeyError out of the gate.
    """
    truncated = dict(_citation(1, 9001, 370001, _CITED_ROWS[0][3]))
    del truncated["evidence_id"]
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(citations=(truncated, _citation(*_CITED_ROWS[1]))),
    )

    failed = _by_name(checks, "citation evidence resolves")
    assert not failed.passed, failed.detail


def test_lab_3_proof_fails_a_citation_whose_evidence_row_changed_revision():
    """Revision is compared too: a quote that moved to another revision fails."""
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            resolved_evidence={
                9001: _evidence_row(9001, 370001, _CITED_ROWS[0][3])
                | {"revision": "2026-09-01"},
                9002: _evidence_row(9002, 429001, _CITED_ROWS[1][3]),
            }
        ),
    )

    assert not _by_name(checks, "citation evidence resolves").passed


def test_lab_3_proof_fails_when_the_evidence_tool_returned_nothing():
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            evidence_events=(
                {"product_id": 370001, "outcome": "success", "result_count": 0},
                {"product_id": 429001, "outcome": "success", "result_count": 3},
            )
        ),
    )

    assert not _by_name(checks, "product evidence retrieved").passed


def test_lab_3_proof_fails_a_search_that_dropped_the_price_ceiling():
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION,
        _persisted_run(
            search_filters=({"domain": "home_office", "in_stock_only": True},)
        ),
    )

    failed = _by_name(checks, "retrieval envelope preserved")
    assert not failed.passed
    assert "max_price_cents" in failed.detail


def test_lab_3_proof_fails_when_no_search_was_persisted():
    """Witness: the envelope loop must not pass over zero persisted searches."""
    checks = lab_checks.lab_3_proof_checks(
        LAB_3_MISSION, _persisted_run(search_filters=())
    )

    assert not _by_name(checks, "retrieval envelope preserved").passed


def test_constraints_preserved_honours_brand_min_rating_and_availability():
    required = {
        "domain": "home_office",
        "brand": "Sonora",
        "min_rating": 4.0,
        "availability": "in_stock",
    }
    assert lab_checks.constraints_preserved(
        required,
        {
            "domain": "home_office",
            "brand": "sonora",
            "min_rating": 4.5,
            "availability": "in_stock",
        },
    )
    assert not lab_checks.constraints_preserved(
        required,
        {
            "domain": "home_office",
            "brand": "Other",
            "min_rating": 4.5,
            "availability": "in_stock",
        },
    )
    assert not lab_checks.constraints_preserved(
        required,
        {
            "domain": "home_office",
            "brand": "Sonora",
            "min_rating": 3.0,
            "availability": "in_stock",
        },
    )


def test_constraints_preserved_accepts_a_narrowed_price_ceiling_by_declaration():
    assert lab_checks.constraints_preserved(
        {"max_price_cents": 80000}, {"max_price_cents": 50000}
    )


def _silent_agent() -> dict:
    """A response that called no tool and recommended nothing."""
    return {"trace": [], "recommendations": [], "citations": []}


def test_lab_3_http_origin_check_fails_on_an_empty_trace():
    """Disclosed strengthening: an empty trace no longer passes vacuously.

    The condition was `not unattributed`, and over zero steps there is nothing
    to be unattributed, so a turn that called no tool at all passed the check
    that exists to prove which calls the model chose.
    """
    checks = lab_checks.agent_response_checks(
        LAB_3_MISSION,
        _silent_agent(),
        AgentEvidence(receipts=(), resolved_evidence={}),
    )

    failed = _by_name(checks, "tool execution origins explicit")
    assert not failed.passed
    assert "empty tool trace" in failed.detail


def test_lab_3_http_evidence_check_fails_when_nothing_was_retrieved():
    """Disclosed strengthening: zero evidence calls no longer pass vacuously.

    The condition was `not missing and not empty`, and over a response that
    recommended nothing both lists are empty, so a turn that fetched no
    evidence graded green on the check that exists to prove it did.
    """
    checks = lab_checks.agent_response_checks(
        LAB_3_MISSION,
        _silent_agent(),
        AgentEvidence(receipts=(), resolved_evidence={}),
    )

    failed = _by_name(checks, "evidence retrieved for every recommendation")
    assert not failed.passed
    assert "no successful get_product_evidence call" in failed.detail


def test_agent_response_checks_count_the_declared_lab_3_conditions():
    """The HTTP validator's Lab 3 vocabulary, evaluated without a transport."""
    agent = {
        "recommendations": [
            {
                "product_id": product_id,
                "domain": "home_office",
                "price_cents": 16999,
                "availability": "in_stock",
                "attributes": {},
            }
            for product_id in (370001, 429001)
        ],
        "trace": [
            {
                "tool": "search_products",
                "outcome": "success",
                "origin": "model",
                "retrieval_run_id": "run-chair",
                "arguments": {
                    "query": "ergonomic chair",
                    "applied_filters": LAB_3_MISSION["filters"],
                },
            },
            {
                "tool": "search_products",
                "outcome": "success",
                "origin": "model",
                "retrieval_run_id": "run-keyboard",
                "arguments": {
                    "query": "quiet mechanical keyboard",
                    "applied_filters": LAB_3_MISSION["filters"],
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
                "arguments": {"search_event_id": "run-chair"},
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
    evidence = AgentEvidence(
        receipts=(
            RetrievalReceipt("run-chair", "ergonomic chair", frozenset({370001})),
            RetrievalReceipt(
                "run-keyboard", "quiet mechanical keyboard", frozenset({429001})
            ),
        ),
        resolved_evidence={
            citation["evidence_id"]: {
                "evidence_id": citation["evidence_id"],
                "product_id": citation["product_id"],
                "evidence_type": citation["evidence_type"],
                "source_uri": citation["source_uri"],
                "revision": citation["revision"],
                "text": citation["quote"],
            }
            for citation in agent["citations"]
        },
    )
    mission = LAB_3_MISSION | {
        "requires_independent_target_searches": True,
        "required_citation_support": [
            {
                "product_id": 370001,
                "evidence_type": "product_spec",
                "all_terms": ["12", "hour"],
            }
        ],
    }

    checks = lab_checks.agent_response_checks(mission, agent, evidence)

    assert len(checks) == 9, (
        f"expected 9 Lab 3 HTTP checks with independent intents declared, "
        f"found {len(checks)}: {_names(checks)}"
    )
    assert all(check.passed for check in checks), _names(
        [check for check in checks if not check.passed]
    )
    assert "independent retrieval intents covered" in _names(checks)
