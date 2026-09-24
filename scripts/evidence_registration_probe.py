"""Check the Lab 3 function's behavior without importing the participant module.

The caller runs this probe in a separate process with a deadline. A malformed
or non-terminating edit must not hang the application that reports lab status.
This is a correctness check, not a sandbox for hostile Python code.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any


def registration_matches_contract(register: Callable[..., None]) -> bool:
    """Exercise stored records, product ownership, repeats and later calls.

    Uses independent records and two products so a constant result, missing map,
    duplicate append or destructive replacement cannot pass on an empty case.
    """
    first = SimpleNamespace(evidence_id=31, product_id=101)
    later = SimpleNamespace(evidence_id=42, product_id=101)
    other = SimpleNamespace(evidence_id=53, product_id=202)
    refreshed = SimpleNamespace(evidence_id=31, product_id=101)
    state: dict[str, Any] = {"evidence": {}, "evidence_by_product": {}}
    register(state, 101, [first, first])
    register(state, 202, [other])
    register(state, 101, [first, later])
    register(state, 101, [refreshed])
    register(state, 101, [])
    return (
        set(state["evidence"]) == {31, 42, 53}
        and state["evidence"][31] is refreshed
        and state["evidence"][42] is later
        and state["evidence"][53] is other
        and state["evidence_by_product"] == {101: [31, 42], 202: [53]}
    )


def main() -> int:
    """Run only the supplied function definition against fresh in-memory records."""
    namespace: dict[str, Any] = {}
    try:
        source = "from __future__ import annotations\n" + sys.stdin.read()
        exec(compile(source, "<participant-register-evidence>", "exec"), namespace)  # noqa: S102
        if not registration_matches_contract(namespace["register_evidence"]):
            return 1
        print("registration checks passed")
        return 0
    except SystemExit:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
