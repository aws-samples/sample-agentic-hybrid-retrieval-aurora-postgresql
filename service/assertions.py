"""The mission assertion vocabulary, in one place, each with its falsifier.

`data/evals/mosaic_labs_missions.json` names the assertions each mission must
satisfy. Before this module the names were strings nobody resolved, so a typo in
the contract was undetectable and — worse — a retrieval arm could fail
completely with every gate green.

`fts_signal_present` exists because that is exactly what happened:
`mosaic_search.search_fts` built an AND-only tsquery, four of the six missions
lost the lexical arm entirely, and no assertion named the lexical arm at all.

Every assertion carries a `falsifier`: the concrete condition under which it
fails. The field is required rather than optional because an assertion whose
failure condition cannot occur is decoration — it reads as evidence while
proving nothing, which is the defect shape this module was created to remove.
Writing the falsifier down is what forces the question to be asked.

Assertions are declared here and scoped per mission by the contract. An arm a
mission does not declare in `expected_techniques` is not asserted, so a
principled abstention stays a pass rather than becoming a false failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Assertion:
    """One assertion: what it proves, and what makes it fail.

    Attributes:
        name: The string a mission puts in its `assertions` list.
        arm: The candidate-generating arm whose signal this proves, or `None`
            when the assertion is about the response envelope rather than one
            arm. Signal assertions are answerable from `candidate_counts`
            alone; envelope assertions are not.
        falsifier: The condition under which this assertion fails. Stated
            concretely, and preferably measured, so the claim can be checked.
    """

    name: str
    arm: str | None
    falsifier: str

    def __post_init__(self) -> None:
        if not self.falsifier.strip():
            raise ValueError(
                f"assertion {self.name!r} has no falsifier; an assertion that "
                f"cannot fail must not be added to the vocabulary"
            )


_ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="fts_signal_present",
        arm="fts",
        falsifier=(
            "the lexical arm contributes no candidates: an AND-only tsquery on "
            "terms that do not co-occur, an unpopulated search_document, or a "
            "dropped GIN index. Measured before Phase 1 on four of six missions."
        ),
    ),
    Assertion(
        name="trigram_signal_present",
        arm="pg_trgm",
        falsifier=(
            "the fuzzy arm contributes no candidates: every eligible product "
            "scores below the 0.20 similarity threshold, or the filter set is "
            "selective enough to empty the pool. Measured at 0 on "
            "hnsw-performance, whose clean query has nothing to recover."
        ),
    ),
    Assertion(
        name="semantic_signal_present",
        arm="hnsw",
        falsifier=(
            "the vector arm contributes no candidates: a partially loaded "
            "embedding column (measured at 50.2% coverage), a failed Bedrock "
            "embed call, a missing HNSW index, or iterative-scan limits that "
            "truncate the pool to nothing. Measured at 0 for hnsw-performance "
            "in a session that skipped mosaic_search.configure_hnsw."
        ),
    ),
    Assertion(
        name="target_in_top_k",
        arm=None,
        falsifier=(
            "the mission's own target is absent from the returned window, so "
            "the run does not demonstrate what the mission claims"
        ),
    ),
    Assertion(
        name="hard_filters_hold",
        arm=None,
        falsifier=(
            "a returned product violates a declared filter — price, stock, "
            "domain, a JSONB attribute, or the refurbished and sponsored "
            "exclusions that apply by default"
        ),
    ),
    Assertion(
        name="rank_provenance_present",
        arm=None,
        falsifier=(
            "a result carries no per-arm rank, so the fused order cannot be "
            "explained and RRF becomes an unauditable score"
        ),
    ),
    Assertion(
        name="rerank_score_present",
        arm=None,
        falsifier=(
            "the rerank stage returns no per-row score: a failed, throttled, or "
            "skipped Bedrock rerank call leaves the final order unexplained"
        ),
    ),
    Assertion(
        name="retrieval_tool_called",
        arm=None,
        falsifier=(
            "the agent answers without calling the typed retrieval tool, which "
            "means it answered from model memory rather than the catalog"
        ),
    ),
    Assertion(
        name="citations_present",
        arm=None,
        falsifier="the answer cites no retrieved evidence",
    ),
    Assertion(
        name="citation_source_revision_present",
        arm=None,
        falsifier=(
            "a citation names no source revision, so the claim cannot be "
            "re-checked against the catalog row that produced it"
        ),
    ),
    Assertion(
        name="measurement_configuration_persisted",
        arm=None,
        falsifier=(
            "a measurement is reported without the configuration that produced "
            "it — ef_search, index type, filter selectivity — making the number "
            "unreproducible"
        ),
    ),
    Assertion(
        name="measurement_kind_declared",
        arm=None,
        falsifier=(
            "a measurement does not say what it measured, so recall and latency "
            "become interchangeable in the record"
        ),
    ),
)

ASSERTIONS: dict[str, Assertion] = {item.name: item for item in _ASSERTIONS}

# Assertion name -> the candidate-generating arm whose signal it proves. Derived
# from the table above rather than declared a second time, so an assertion cannot
# exist in one collection and be missing from the other.
SIGNAL_ASSERTIONS: dict[str, str] = {
    item.name: item.arm for item in _ASSERTIONS if item.arm is not None
}

# Everything else is about the response envelope rather than one arm, so it is
# not resolvable from candidate counts. `rerank_score_present` belongs here: it
# reads a per-row score, not a pool size.
ENVELOPE_ASSERTIONS: frozenset[str] = frozenset(
    item.name for item in _ASSERTIONS if item.arm is None
)

KNOWN_ASSERTIONS: frozenset[str] = frozenset(ASSERTIONS)

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


def falsifier_for(name: str) -> str:
    """The condition under which the named assertion fails.

    Raises:
        UnknownAssertionError: the name is not in the vocabulary.
    """
    try:
        return ASSERTIONS[name].falsifier
    except KeyError:
        raise UnknownAssertionError(
            f"unknown assertion {name!r}; add it to service.assertions with a "
            f"falsifier, or fix the caller"
        ) from None


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
