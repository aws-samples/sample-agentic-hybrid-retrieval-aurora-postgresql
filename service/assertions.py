"""The mission assertion vocabulary, in one place, each with its falsifier.

`data/evals/mosaic_labs_missions.json` names the assertions each mission must
satisfy. Before this module the names were strings nobody resolved, so a typo in
the contract was undetectable and — worse — a retrieval arm could fail
completely with every gate green.

`fts_signal_present` exists because the lexical arm can fail completely:
`search_fts` runs a strict AND query with a conjunctive backoff; it never
OR-combines. Under the AND-only tsquery that shipped before the backoff
existed, the missions that then declared `fts` lost the lexical arm entirely,
and no assertion named the lexical arm at all.

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
        label: What it proves in plain words, as a participant reads it on a
            check line; `{top_k}` is filled with the request's result window.
            The name stays the contract key, so a label can change freely.
    """

    name: str
    arm: str | None
    falsifier: str
    label: str

    def __post_init__(self) -> None:
        if not self.falsifier.strip():
            raise ValueError(
                f"assertion {self.name!r} has no falsifier; an assertion that "
                f"cannot fail must not be added to the vocabulary"
            )
        shown = self.label.replace("{top_k}", "10")
        if not shown.strip() or "_" in shown:
            raise ValueError(
                f"assertion {self.name!r} has label {self.label!r}; fix: say what "
                f"it proves in plain words, without the key's underscores"
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
        label="full-text search contributed candidates",
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
        label="fuzzy matching contributed candidates",
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
        label="semantic search contributed candidates",
    ),
    Assertion(
        name="target_in_top_k",
        arm=None,
        falsifier=(
            "the mission's own target is absent from the returned window, so "
            "the run does not demonstrate what the mission claims"
        ),
        label="right product in the top {top_k}",
    ),
    Assertion(
        name="hard_filters_hold",
        arm=None,
        falsifier=(
            "a returned product violates a declared filter — price, stock, "
            "domain, a JSONB attribute, or the refurbished and sponsored "
            "exclusions that apply by default"
        ),
        label="every result inside the filters",
    ),
    Assertion(
        name="rank_provenance_present",
        arm=None,
        falsifier=(
            "a result carries no per-arm rank, so the fused order cannot be "
            "explained and RRF becomes an unauditable score"
        ),
        label="every result keeps its combined and final positions",
    ),
    Assertion(
        name="rerank_score_present",
        arm=None,
        falsifier=(
            "the rerank stage returns no per-row score: a failed, throttled, or "
            "skipped Bedrock rerank call leaves the final order unexplained"
        ),
        label="the reranker scored every result",
    ),
    Assertion(
        name="structured_constraints_extracted",
        arm=None,
        falsifier=(
            "no successful search_products trace preserves the request's "
            "domain, price ceiling, stock constraint, and any declared "
            "category_key, brand, min_rating, availability, or attributes; "
            "a narrowed price "
            "ceiling still passes, since a tighter bound is not a widened "
            "request. The Lab 3 core mission declares no attribute, so the "
            "decisive attribute check on that mission is carried by the "
            "evidence-grounding supporting check, not by this assertion"
        ),
        label="the search kept the request's filters",
    ),
    Assertion(
        name="retrieval_tool_called",
        arm=None,
        falsifier=(
            "the agent answers without calling the typed retrieval tool, which "
            "means it answered from model memory rather than the catalog"
        ),
        label="the agent searched the catalog",
    ),
    Assertion(
        name="expected_products_considered",
        arm=None,
        falsifier=(
            "none of the target products named in the test appears in the saved "
            "candidate receipts for the agent's retrieval runs"
        ),
        label="the expected products were considered",
    ),
    Assertion(
        name="comparison_tool_called",
        arm=None,
        falsifier=(
            "the agent recommends among competing products without a successful "
            "compare_products call over IDs returned by retrieval"
        ),
        label="the agent compared the products",
    ),
    Assertion(
        name="evidence_tool_called",
        arm=None,
        falsifier=(
            "the agent reaches synthesis without a successful "
            "get_product_evidence call for each recommended product"
        ),
        label="the agent read each recommended product's sources",
    ),
    Assertion(
        name="evidence_records_returned",
        arm=None,
        falsifier=(
            "an evidence tool succeeds with zero records, leaving synthesis "
            "without source-addressable support"
        ),
        label="the source reads returned records",
    ),
    Assertion(
        name="ranking_explanation_available",
        arm=None,
        falsifier=(
            "the agent has anything other than one successful "
            "explain_retrieval receipt before synthesis, so its ranking "
            "explanation cannot be tied to the tool contract"
        ),
        label="the agent read the ranking explanation",
    ),
    Assertion(
        name="recommendation_grounded",
        arm=None,
        falsifier=(
            "a recommended product was not returned by this run's retrieval or "
            "has no successfully retrieved evidence before synthesis"
        ),
        label="every recommendation came from this run's search",
    ),
    Assertion(
        name="citations_present",
        arm=None,
        falsifier="the answer cites no retrieved evidence",
        label="the answer cites sources",
    ),
    Assertion(
        name="citation_ids_resolve",
        arm=None,
        falsifier=(
            "a returned citation evidence_id does not resolve to a real "
            "product_evidence row for the citation's product"
        ),
        label="every citation points at a real source",
    ),
    Assertion(
        name="citation_claims_supported",
        arm=None,
        falsifier=(
            "a mission-owned factual claim has no citation for the required "
            "product and evidence type whose resolved text contains every "
            "declared support term"
        ),
        label="each cited source contains its claim",
    ),
    Assertion(
        name="citation_source_revision_present",
        arm=None,
        falsifier=(
            "a citation names no source revision, so the claim cannot be "
            "re-checked against the catalog row that produced it"
        ),
        label="every citation names its source revision",
    ),
    Assertion(
        name="measurement_configuration_persisted",
        arm=None,
        falsifier=(
            "a measurement is reported without the configuration that produced "
            "it — ef_search, index type, filter selectivity — making the number "
            "unreproducible"
        ),
        label="the measurement saved its settings",
    ),
    Assertion(
        name="measurement_kind_declared",
        arm=None,
        falsifier=(
            "a measurement does not say what it measured, so recall and latency "
            "become interchangeable in the record"
        ),
        label="the measurement says what it measured",
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


def label_for(name: str, *, top_k: int) -> str:
    """What the named assertion proves, in plain words, for a request's result window.

    Raises:
        UnknownAssertionError: the name is not in the vocabulary.
    """
    try:
        return ASSERTIONS[name].label.format(top_k=top_k)
    except KeyError:
        raise UnknownAssertionError(
            f"unknown assertion {name!r}; add it to service.assertions with a "
            f"label, or fix the caller"
        ) from None


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
