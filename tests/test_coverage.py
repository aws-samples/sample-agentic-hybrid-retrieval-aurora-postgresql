"""A guardrail that fires on the workshop's own headline query is a regression.

The coverage gate exists to stop `replacement charging brick for model A2342`
being answered with generic chargers. The failure mode that matters more is the
opposite one: `noice cancelng hedfones` has the same surface property -- every
token matches zero documents -- and it is Lab 1's entire lesson. A gate that
cannot tell those apart destroys the workshop.

So the falsifier is permanent and it is first: an all-misspelled request must
stay `grounded`.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from service import coverage
from service.coverage import (
    QueryCoverage,
    TermCoverage,
    summarize,
    unanchored_note,
)


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

    def execute(self, sql, params=None):
        self.executed.append(sql)
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


def test_explicit_floor_is_passed_through(fake_connect):
    connection = fake_connect(_FakeConnection(ready=True, rows=[]))
    coverage.assess("anything", word_similarity_floor=0.6)
    assert any("%s, %s" in sql for sql in connection.executed)


def test_default_floor_omits_the_argument(fake_connect):
    """The SQL default is the single declaration of an unmeasured number.
    Passing a Python-side copy would create a second one."""
    connection = fake_connect(_FakeConnection(ready=True, rows=[]))
    coverage.assess("anything")
    coverage_sql = [s for s in connection.executed if "query_term_coverage" in s]
    assert coverage_sql and all("%s, %s" not in sql for sql in coverage_sql)


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
