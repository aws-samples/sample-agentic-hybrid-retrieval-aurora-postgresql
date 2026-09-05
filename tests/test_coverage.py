"""A guardrail that fires on the workshop's own headline query is a regression.

The coverage gate exists to stop `replacement charging brick for model A2342`
being answered with generic chargers. The failure mode that matters more is the
opposite one: `noice cancelng hedfones` has the same surface property -- every
token matches zero documents -- and it is Lab 1's entire lesson. A gate that
cannot tell those apart destroys the workshop.

So the falsifier is permanent and it is first: an all-misspelled request must
stay `grounded`.

Everything above `test_the_yaml_floor_equals_the_sql_default` runs without a
database. The `aurora`-marked tests below it run every case in
`data/evals/coverage_queries.jsonl` against the live cluster, which is the only
place the floor can actually be falsified: the pure functions here classify
verdicts they are handed, and the verdict is what the SQL decides.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from scripts.config_tripwire import SQL_DEFAULTS, _sql_default
from scripts.retrieval_profile import load_profile
from service import coverage
from service.coverage import (
    QueryCoverage,
    TermCoverage,
    summarize,
    unanchored_note,
)

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_SQL = ROOT / "db" / "sql" / "20_query_coverage.sql"
COVERAGE_QUERIES = ROOT / "data" / "evals" / "coverage_queries.jsonl"

#: Token kinds `mosaic_search.is_identifier_token` refuses to rescue. Written
#: out rather than read from the SQL, so a branch deleted there fails here.
IDENTIFIER_KINDS = (
    "numword",
    "numhword",
    "uint",
    "int",
    "float",
    "sfloat",
    "version",
    "file",
    "url",
    "url_path",
    "host",
    "email",
)


def _cases() -> list[dict]:
    return [
        json.loads(line)
        for line in COVERAGE_QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _term(
    token: str,
    verdict: str,
    *,
    ordinal: int = 1,
    token_kind: str = "asciiword",
    ndoc: int = 0,
    closest_lexeme: str | None = None,
    closest_similarity: float | None = None,
) -> TermCoverage:
    return TermCoverage(
        ordinal=ordinal,
        token=token,
        token_kind=token_kind,
        lexeme=token.lower(),
        ndoc=ndoc,
        closest_lexeme=closest_lexeme,
        closest_similarity=closest_similarity,
        verdict=verdict,
    )


#: Lab 1's query as `mosaic_search.query_term_coverage` classifies it. Every
#: token has ndoc=0; every token has a close catalog neighbour. This is the
#: permanent falsifier -- if the gate ever fires here, the gate is wrong.
LAB1_MISSPELLED_TERMS = [
    _term(
        "noice",
        "recoverable",
        ordinal=1,
        closest_lexeme="nois",
        closest_similarity=0.55,
    ),
    _term(
        "cancelng",
        "recoverable",
        ordinal=2,
        closest_lexeme="cancel",
        closest_similarity=0.62,
    ),
    _term(
        "hedfones",
        "recoverable",
        ordinal=3,
        closest_lexeme="headphon",
        closest_similarity=0.47,
    ),
]

#: The reported query. `a2342` parses as `numword`, so no trigram neighbour can
#: rescue it: a near model number is a different product.
CHARGING_BRICK_TERMS = [
    _term("replacement", "matched", ordinal=1, ndoc=1840),
    _term("charging", "matched", ordinal=2, ndoc=9120),
    _term("brick", "matched", ordinal=3, ndoc=210),
    _term("model", "matched", ordinal=4, ndoc=44000),
    _term("A2342", "unmatched_anchor", ordinal=5, token_kind="numword"),
]


def test_all_misspelled_query_stays_grounded():
    """The Lab 1 falsifier. Zero exact matches is not evidence of absence."""
    result = summarize(LAB1_MISSPELLED_TERMS)
    assert result.confidence == "grounded"
    assert result.unmatched_terms == []
    assert result.is_anchored is True


def test_absent_model_number_is_unanchored():
    result = summarize(CHARGING_BRICK_TERMS)
    assert result.confidence == "unanchored"
    assert result.unmatched_terms == ["A2342"]
    assert result.is_anchored is False


def test_unanchored_note_names_the_term_not_the_mechanism():
    """A shopper reads this. It must not say 'lexeme' or 'trigram'."""
    result = summarize(CHARGING_BRICK_TERMS)
    assert "A2342" in result.note
    for mechanism in ("lexeme", "trigram", "tsvector", "ndoc"):
        assert mechanism not in result.note.lower()


def test_note_is_empty_when_grounded():
    assert summarize(LAB1_MISSPELLED_TERMS).note == ""
    assert unanchored_note([]) == ""


def test_note_pluralizes_on_multiple_unmatched_terms():
    terms = [
        _term("A2342", "unmatched_anchor", ordinal=1, token_kind="numword"),
        _term("X9911", "unmatched_anchor", ordinal=2, token_kind="numword"),
    ]
    result = summarize(terms)
    assert result.unmatched_terms == ["A2342", "X9911"]
    assert "terms 'A2342', 'X9911'" in result.note


def test_matched_and_ignored_terms_alone_are_grounded():
    terms = [
        _term("the", "ignored", ordinal=1),
        _term("chargers", "matched", ordinal=2, ndoc=9120),
    ]
    assert summarize(terms).confidence == "grounded"


def test_one_unmatched_anchor_among_matches_still_unanchored():
    """Partial anchoring is the actual failure. Most of the query matching is
    exactly what makes the wrong answer look right."""
    result = summarize(CHARGING_BRICK_TERMS)
    matched = [t for t in CHARGING_BRICK_TERMS if t.verdict == "matched"]
    assert len(matched) == 4
    assert result.confidence == "unanchored"


def test_empty_term_list_is_grounded_not_unanchored():
    """A request with nothing to classify has named nothing absent."""
    assert summarize([]).confidence == "grounded"


def test_summarize_preserves_every_term_for_inspection():
    result = summarize(CHARGING_BRICK_TERMS)
    assert [t.token for t in result.terms] == [
        "replacement",
        "charging",
        "brick",
        "model",
        "A2342",
    ]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """Answers the readiness probe, then the coverage query."""

    def __init__(self, *, ready: bool, rows: list[dict] | None = None):
        self._ready = ready
        self._rows = rows or []
        self.executed: list[str] = []
        self.parameters: list[tuple | None] = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        self.parameters.append(params)
        if "corpus_lexeme" in sql and "EXISTS" in sql:
            return _FakeCursor([{"ready": self._ready}])
        return _FakeCursor(self._rows)


@pytest.fixture
def fake_connect(monkeypatch):
    def _install(connection):
        @contextmanager
        def _connect():
            yield connection

        monkeypatch.setattr(coverage, "connect", _connect)
        return connection

    return _install


def test_unseeded_vocabulary_is_unavailable_never_unanchored(fake_connect):
    """The catastrophic edge case.

    An empty `corpus_lexeme` makes every term look absent. Reporting that as
    `unanchored` would refuse every request on a deployment whose only fault is
    a missing seed step -- turning one skipped procedure into a total outage
    that presents as a working guardrail.
    """
    fake_connect(_FakeConnection(ready=False))
    result = coverage.assess("replacement charging brick for model A2342")
    assert result.confidence == "unavailable"
    assert result.unmatched_terms == []
    assert result.is_anchored is True
    assert "refresh_corpus_lexeme" in result.note


def test_blank_query_never_touches_the_database(fake_connect):
    connection = fake_connect(_FakeConnection(ready=True))
    assert coverage.assess("   ").confidence == "grounded"
    assert connection.executed == []


def test_assess_maps_sql_rows_to_verdicts(fake_connect):
    fake_connect(
        _FakeConnection(
            ready=True,
            rows=[
                {
                    "ordinal": 1,
                    "token": "charging",
                    "token_kind": "asciiword",
                    "lexeme": "charg",
                    "ndoc": 9120,
                    "closest_lexeme": None,
                    "closest_similarity": None,
                    "verdict": "matched",
                },
                {
                    "ordinal": 2,
                    "token": "A2342",
                    "token_kind": "numword",
                    "lexeme": "a2342",
                    "ndoc": 0,
                    "closest_lexeme": None,
                    "closest_similarity": None,
                    "verdict": "unmatched_anchor",
                },
            ],
        )
    )
    result = coverage.assess("charging A2342")
    assert result.confidence == "unanchored"
    assert result.unmatched_terms == ["A2342"]


def test_an_explicit_floor_wins_over_the_yaml(fake_connect):
    connection = fake_connect(_FakeConnection(ready=True, rows=[]))
    coverage.assess("anything", similarity_floor=0.6)
    assert connection.parameters[-1][1] == 0.6


def test_the_default_floor_is_the_yaml_value_and_is_always_sent(fake_connect):
    """The floor reaches the database on every call, never by omission.

    Leaving it out would hand the verdict to whatever default the cluster
    happens to hold. They agree today and `scripts/config_tripwire.py` keeps
    them agreeing, but "the number the yaml declares" and "the number this
    cluster was last installed with" are different claims, and only one of them
    is checkable from here.
    """
    connection = fake_connect(_FakeConnection(ready=True, rows=[]))
    coverage.assess("anything")
    coverage_sql = [s for s in connection.executed if "query_term_coverage" in s]
    assert coverage_sql and all("%s, %s::real" in sql for sql in coverage_sql)
    assert connection.parameters[-1][1] == load_profile().coverage_similarity_floor


def test_the_yaml_floor_equals_the_sql_default():
    """Rule 5: exempt from declaring, never from agreeing.

    Read through `scripts.config_tripwire._sql_default`, the parser the gate
    itself uses, rather than a second regex written here -- a test that
    re-derives production logic stops discriminating the moment production
    changes shape.
    """
    entry = next(
        d
        for d in SQL_DEFAULTS
        if d.file == "20_query_coverage.sql" and d.parameter == "similarity_floor"
    )
    assert entry.profile_field == "coverage_similarity_floor"
    declared = _sql_default(COVERAGE_SQL.read_text(encoding="utf-8"), entry)
    assert declared is not None, "query_term_coverage lost its similarity_floor default"
    assert float(declared) == load_profile().coverage_similarity_floor


@pytest.mark.parametrize("kind", IDENTIFIER_KINDS)
def test_an_identifier_token_is_refused_however_close_its_neighbour(kind):
    """A model number near another model number is a different product.

    Hand-built verdicts, so this holds at every floor: the rows carry a
    neighbour at similarity 0.99, far above any floor the yaml could declare,
    and the summary must still refuse. It fails the moment anything in the
    Python layer starts re-deriving recoverability from `closest_similarity`
    instead of reading the verdict the SQL reached.
    """
    result = summarize(
        [
            _term("charger", "matched", ordinal=1, ndoc=9120),
            _term(
                "A2343",
                "unmatched_anchor",
                ordinal=2,
                token_kind=kind,
                closest_lexeme="a2342",
                closest_similarity=0.99,
            ),
        ]
    )
    assert result.confidence == "unanchored"
    assert result.unmatched_terms == ["A2343"]


def test_the_sql_refuses_identifiers_before_it_consults_the_floor():
    """The branch order is the rule; a floor comparison reached first would
    rescue a model number by proximity to a different one."""
    body = COVERAGE_SQL.read_text(encoding="utf-8")
    case = body.split("CASE", 1)[1].split("END AS verdict", 1)[0]
    identifier = case.index("is_identifier_token")
    floor = case.index("similarity_floor")
    assert identifier < floor, (
        "found the similarity_floor branch ahead of the identifier branch in "
        "query_term_coverage; fix: keep is_identifier_token first, or an "
        "absent model number becomes recoverable"
    )


def test_the_neighbour_lookup_reads_the_surface_vocabulary():
    """Measured 2026-09-04: against the stemmed vocabulary the Lab 1 anchor's
    'hedfones' and the out-of-domain 'quarterly' both score 0.231, so no floor
    separates C-101 from C-006. Reverting the lookup to corpus_lexeme reverts
    that, silently, with every offline test still green."""
    body = COVERAGE_SQL.read_text(encoding="utf-8")
    lookup = body.split("LEFT JOIN LATERAL (", 1)[1].split(") AS near", 1)[0]
    assert "mosaic_search.corpus_surface_lexeme" in lookup
    assert re.search(r"mosaic_search\.corpus_lexeme\b", lookup) is None


def test_coverage_model_rejects_an_unknown_verdict():
    with pytest.raises(ValueError):
        TermCoverage(
            ordinal=1,
            token="x",
            token_kind="asciiword",
            verdict="probably_fine",
        )


def test_default_coverage_is_grounded_and_serializable():
    payload = QueryCoverage(confidence="grounded").model_dump()
    assert payload["unmatched_terms"] == []
    assert payload["terms"] == []


class _UnmigratedConnection:
    """A cluster provisioned before db/sql/20_query_coverage.sql existed."""

    def __init__(self, error: type[Exception]):
        self._error = error

    def execute(self, sql, params=None):
        raise self._error("relation does not exist")


@pytest.mark.parametrize(
    "error",
    [psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction],
    ids=["no-vocabulary-table", "no-coverage-function"],
)
def test_an_unmigrated_database_keeps_serving(fake_connect, error):
    """Coverage is an enhancement to search, never a dependency of it.

    Every existing Aurora cluster lacks the table and the function until
    `make db-install` runs again. If that raised, coverage would take down
    every search on every deployed workshop the moment this code shipped.
    """
    fake_connect(_UnmigratedConnection(error))
    result = coverage.assess("replacement charging brick for model A2342")
    assert result.confidence == "unavailable"
    assert result.is_anchored is True
    assert "db-install" in result.note


def test_a_real_database_error_is_not_swallowed(fake_connect):
    """Only the two migration errors degrade. A connection or syntax failure is
    a genuine fault and must not be reported as `unavailable`, which would hide
    a broken database behind a benign-looking label."""
    fake_connect(_UnmigratedConnection(psycopg.errors.InsufficientPrivilege))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        coverage.assess("anything")


def test_assess_uses_an_injected_connection_factory():
    """`RetrievalService` passes its own factory so coverage reaches the same
    database the search did, rather than falling through to the shared pool."""
    connection = _FakeConnection(ready=True, rows=[])
    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield connection

    coverage.assess("anything", connection_factory=factory)
    assert any("query_term_coverage" in sql for sql in connection.executed)


# --- Live calibration ---------------------------------------------------
#
# The floor is a number about a corpus. Nothing offline can falsify it: every
# test above is handed verdicts, and the verdict is what the floor decides. So
# the calibration is asserted where it was measured, against the 500,000-product
# cluster, and the recorded `measured` block in the eval file is asserted term by
# term rather than only in summary -- a case whose confidence is right for the
# wrong reason is the failure this set exists to catch.

VERIFIED_CASES = [case for case in _cases() if case["verified_against_catalog"]]


def test_the_live_calibration_has_cases_to_assert():
    """Witness. A parametrize over an empty list passes while proving nothing,
    which is exactly how eight gates in this repository were green on broken."""
    assert VERIFIED_CASES, (
        "no case claims live verification; the aurora tests are inert"
    )
    assert len(VERIFIED_CASES) == len(_cases())


@pytest.mark.aurora
@pytest.mark.parametrize("case", VERIFIED_CASES, ids=lambda c: c["query_id"])
def test_every_verified_case_classifies_as_recorded(case):
    """Both halves: the expectation the set declares, and the run that verified it."""
    measured = case["measured"]
    assert measured["similarity_floor"] == load_profile().coverage_similarity_floor, (
        f"{case['query_id']} was measured at {measured['similarity_floor']} but the "
        f"yaml now declares {load_profile().coverage_similarity_floor}; fix: re-measure "
        f"the set against the live cluster before changing the floor"
    )
    result = coverage.assess(case["query"])
    assert result.confidence == case["expected_confidence"]
    assert result.confidence == measured["confidence"]
    assert result.unmatched_terms == measured["unmatched_terms"]
    if case["expected_unmatched_terms"]:
        assert result.unmatched_terms == case["expected_unmatched_terms"]
    if case["expected_confidence"] == "grounded":
        assert result.unmatched_terms == []

    assert result.terms, f"{case['query_id']} produced no terms to inspect"
    assert len(result.terms) == len(measured["terms"])
    for term, recorded in zip(result.terms, measured["terms"], strict=True):
        assert term.token == recorded["token"]
        assert term.token_kind == recorded["kind"]
        assert term.verdict == recorded["verdict"], (
            f"{case['query_id']} token {term.token!r} is now {term.verdict!r}, "
            f"recorded as {recorded['verdict']!r} on {measured['measured_on']}"
        )
        assert term.ndoc == recorded["ndoc"]
        if "closest" in recorded:
            assert term.closest_lexeme == recorded["closest"]
            assert round(float(term.closest_similarity), 3) == recorded["similarity"]


@pytest.mark.aurora
def test_the_floor_is_what_decides_the_lab_1_anchor():
    """Red-at-birth, kept permanent. The anchor is grounded at the shipped floor
    and refused above its narrowest token, so a green result here is evidence
    that the floor is load-bearing rather than that nothing was tested.

    Measured 2026-09-04: 'hedfones' reaches 'hedphones' at 0.462.
    """
    anchor = "noice cancelng hedfones"
    assert coverage.assess(anchor).confidence == "grounded"
    refused = coverage.assess(anchor, similarity_floor=0.5)
    assert refused.confidence == "unanchored"
    assert refused.unmatched_terms == ["hedfones"]


@pytest.mark.aurora
def test_the_floor_is_what_decides_the_invented_brand():
    """The other end of the calibration. 'Zylthorne' clears 0.231 and nothing
    more, so a floor at 0.2 admits it and the guardrail stops guarding."""
    query = "Zylthorne over-ear headphones"
    assert coverage.assess(query).unmatched_terms == ["Zylthorne"]
    assert coverage.assess(query, similarity_floor=0.2).confidence == "grounded"


@pytest.mark.aurora
@pytest.mark.parametrize("floor", [0.01, 0.24, 0.99])
def test_an_absent_model_number_is_refused_at_every_floor(floor):
    """The half of this gate that does not rest on a 0.019 margin. `a2342` is a
    numword, so the neighbour lookup never runs for it."""
    result = coverage.assess(
        "I need a replacement charging brick for model A2342", similarity_floor=floor
    )
    assert result.confidence == "unanchored"
    assert "A2342" in result.unmatched_terms


@pytest.mark.aurora
def test_both_vocabularies_are_seeded_on_this_cluster():
    """`assess` reports `unavailable` when either table is empty, which would make
    every assertion above vacuously pass on a half-seeded database."""
    result = coverage.assess("wireless headphones")
    assert result.confidence != "unavailable", result.note
