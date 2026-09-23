"""Fixtures for the Lab 3 evidence-contract tests.

`scripts/lab_exercise.py check --lab 3` runs these tests several times: against
the reference repair, against faulty variants, and against your code. Always
call the function under test through the `register` fixture.
"""

import os
from types import SimpleNamespace

import pytest

from service import agent_tools


@pytest.fixture
def register():
    """The `register_evidence` implementation under test."""
    variant = os.environ.get("LAB3_VARIANT")
    if not variant:
        return agent_tools.register_evidence
    from scripts.lab_exercise import variant_function

    return variant_function(variant)


@pytest.fixture
def state():
    """The two per-turn maps synthesis reads, empty at the start of a turn."""
    return {"evidence": {}, "evidence_by_product": {}}


def record(evidence_id: int, product_id: int) -> SimpleNamespace:
    """A retrieved evidence record; synthesis keys it by `evidence_id`."""
    return SimpleNamespace(evidence_id=evidence_id, product_id=product_id)
