from types import SimpleNamespace

import pytest

from scripts.measure_query_coverage import measure_cases


def test_measurement_preserves_requests_and_rejects_changed_expectations():
    case = {
        "query_id": "case",
        "query": "missing model X123",
        "expected_confidence": "unanchored",
        "expected_unmatched_terms": ["X123"],
    }
    term = SimpleNamespace(
        token="X123",
        token_kind="numword",
        ndoc=0,
        verdict="unmatched_anchor",
        closest_lexeme=None,
    )
    result = SimpleNamespace(
        confidence="unanchored", unmatched_terms=["X123"], terms=[term]
    )
    queries = []

    def assess(query):
        queries.append(query)
        return result

    measured = measure_cases([case], assess=assess, metadata={})
    assert queries == [case["query"]]
    assert all(measured[0][key] == value for key, value in case.items())
    assert "measured" not in case
    result.confidence = "grounded"
    with pytest.raises(ValueError, match="Coverage expectation rule"):
        measure_cases([case], assess=assess, metadata={})
    assert "measured" not in case
    result.confidence = "unanchored"
    result.terms = []
    with pytest.raises(ValueError, match="term witness rule"):
        measure_cases([case], assess=assess, metadata={})


def test_no_cases_cannot_produce_a_verified_measurement():
    with pytest.raises(ValueError, match="Coverage witness rule"):
        measure_cases([], assess=lambda _: None, metadata={})
