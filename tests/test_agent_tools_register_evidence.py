"""Evidence is authorized for citation only under the product it describes."""

from __future__ import annotations

import pytest

from service.agent_tools import register_evidence
from service.models import EvidenceRecord


def _record(evidence_id: int, product_id: int) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        product_id=product_id,
        evidence_type="specification",
        source_name="Maker",
        source_uri="https://example.invalid/spec",
        revision="r1",
        title="Specification sheet",
        text="Battery life 20 hours.",
    )


def test_registration_files_each_record_under_its_own_product():
    state = {"evidence": {}, "evidence_by_product": {}}
    register_evidence(state, 1, [_record(10, 1)])
    register_evidence(state, 1, [_record(10, 1)])
    assert state["evidence_by_product"] == {1: [10]}


def test_a_record_of_another_product_is_refused_and_nothing_is_registered():
    """Falsifier: without the check, product 2's record becomes citable for product 1."""
    state = {"evidence": {}, "evidence_by_product": {}}
    with pytest.raises(ValueError, match=r"product 2, not product 1"):
        register_evidence(state, 1, [_record(10, 1), _record(11, 2)])
    assert state == {"evidence": {}, "evidence_by_product": {}}
