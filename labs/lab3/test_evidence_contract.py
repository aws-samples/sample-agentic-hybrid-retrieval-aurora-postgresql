"""Lab 3: specify the evidence contract before you repair it.

Contract for `register_evidence(state, product_id, evidence)`:

1. Every returned record is stored in `state["evidence"]` under its ID.
2. Its ID is listed under the product it was retrieved for in
   `state["evidence_by_product"]`.
3. Calling it again for the same product never lists an ID twice.
4. A later call adds to what an earlier call registered; it never drops IDs.

The first test is an example. Add at least two more that pin down clauses 3
and 4, then grade them:

    uv run python scripts/lab_exercise.py check --lab 3

The grader runs your tests against the reference repair (they must pass),
against faulty implementations (each must be rejected by some test), and
against your code.
"""

from labs.lab3.conftest import record


def test_records_are_authorized_for_their_product(register, state):
    monitor = 1408222
    register(state, monitor, [record(11, monitor), record(12, monitor)])

    assert set(state["evidence"]) == {11, 12}
    assert state["evidence_by_product"][monitor] == [11, 12]
