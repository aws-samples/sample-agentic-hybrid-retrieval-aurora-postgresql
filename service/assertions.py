"""The mission assertion vocabulary, in one place.

`data/evals/mosaic_labs_missions.json` names the assertions each mission must
satisfy. Before this module the names were strings nobody resolved, so a typo in
the contract was undetectable and — worse — a retrieval arm could fail
completely with every gate green.

`fts_signal_present` exists because that is exactly what happened:
`mosaic_search.search_fts` built an AND-only tsquery, four of the six missions
lost the lexical arm entirely, and no assertion named the lexical arm at all.

Assertions are declared here and scoped per mission by the contract. An arm a
mission does not declare in `expected_techniques` is not asserted, so a
principled abstention stays a pass rather than becoming a false failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# Assertion name -> the candidate-generating arm whose signal it proves. Each of
# these is answerable from `candidate_counts` alone.
SIGNAL_ASSERTIONS: dict[str, str] = {
    "fts_signal_present": "fts",
    "trigram_signal_present": "pg_trgm",
    "semantic_signal_present": "hnsw",
}

# Everything else is about the response envelope rather than one arm, so it is
# not resolvable from candidate counts. `rerank_score_present` belongs here: it
# reads a per-row score, not a pool size.
ENVELOPE_ASSERTIONS: frozenset[str] = frozenset(
    {
        "target_in_top_k",
        "hard_filters_hold",
        "rank_provenance_present",
        "rerank_score_present",
        "retrieval_tool_called",
        "citations_present",
        "citation_source_revision_present",
        "measurement_configuration_persisted",
        "measurement_kind_declared",
    }
)

KNOWN_ASSERTIONS: frozenset[str] = frozenset(SIGNAL_ASSERTIONS) | ENVELOPE_ASSERTIONS

# Technique -> the key `service.retrieval` reports it under in
# `RetrievalDiagnostics.candidate_counts`. These names are the engine's, not this
# module's; a rename there must be mirrored here or the assertion reads a
# missing key and silently passes.
_ARM_COUNT_KEY: dict[str, str] = {
    "fts": "fts_in_pool",
    "pg_trgm": "trigram_in_pool",
    "hnsw": "semantic_in_pool",
}


class UnknownAssertionError(ValueError):
    """A mission named an assertion this module does not define."""


def signal_assertions_for(expected_techniques: Sequence[str]) -> list[str]:
    """Signal assertions a mission is entitled to, given the arms it declares.

    A mission that does not declare `fts` is not asserted on the lexical arm:
    its recovery is a side effect of the fix, not a requirement.
    """
    declared = set(expected_techniques)
    return [
        name for name, technique in SIGNAL_ASSERTIONS.items() if technique in declared
    ]


def arm_signal_present(candidate_counts: Mapping[str, int], technique: str) -> bool:
    """True when the named arm actually contributed candidates.

    A zero count is the failure this module exists to catch: the arm ran, the
    index was fine, and it matched nothing.
    """
    key = _ARM_COUNT_KEY.get(technique, technique)
    return candidate_counts.get(key, 0) > 0


def evaluate_signal_assertions(
    mission: Mapping[str, object],
    candidate_counts: Mapping[str, int],
) -> dict[str, bool]:
    """Resolve every signal assertion the mission declares.

    Raises:
        UnknownAssertionError: the mission names an assertion not defined here,
            which means the contract and the code have drifted apart.
    """
    declared = list(mission.get("assertions") or [])
    unknown = [name for name in declared if name not in KNOWN_ASSERTIONS]
    if unknown:
        raise UnknownAssertionError(
            f"mission {mission.get('id')!r} names unknown assertion(s) {unknown}; "
            f"add them to service.assertions or fix the contract"
        )
    return {
        name: arm_signal_present(candidate_counts, SIGNAL_ASSERTIONS[name])
        for name in declared
        if name in SIGNAL_ASSERTIONS
    }
