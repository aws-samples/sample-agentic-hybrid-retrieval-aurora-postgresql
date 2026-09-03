"""Whether a request named anything the catalog does not carry.

`mosaic_search.search_fts` selects salient terms with an EXISTS against
`product_document`, so a term matching zero documents is dropped before the
backoff loop runs. Retrieval then answers whatever survived. Reciprocal rank
fusion weights by position rather than by score, so nothing downstream can
recover the fact that the dropped term was the one carrying the identity:
`replacement charging brick for model A2342` loses `a2342` and returns
chargers, ranked confidently.

This module keeps that signal. It classifies, it does not filter. A request
naming an absent model still returns its closest products, labelled, because a
shopper looking for an A2342 brick is better served by 65W chargers under a
caveat than by an empty page. What the label changes is authority: an
unanchored request may not produce a cited answer of record.

The verdicts come from `mosaic_search.query_term_coverage`; see
`db/sql/20_query_coverage.sql` for how a misspelling is separated from an
absence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from service.db import connect

#: A term matching nothing, which nothing can recover. The request names
#: something outside the catalog.
UNMATCHED_ANCHOR = "unmatched_anchor"

#: A term matching nothing exactly, but close enough to a catalog term for the
#: trigram arm to reach it. Lab 1's `noice cancelng hedfones` is entirely this.
RECOVERABLE = "recoverable"

MATCHED = "matched"
IGNORED = "ignored"

CoverageConfidence = Literal["grounded", "unanchored", "unavailable"]


class TermCoverage(BaseModel):
    """One parsed request token, and what the catalog holds for it."""

    ordinal: int
    token: str
    token_kind: str
    lexeme: str | None = None
    ndoc: int = 0
    closest_lexeme: str | None = None
    closest_similarity: float | None = None
    verdict: Literal["matched", "recoverable", "unmatched_anchor", "ignored"]


class QueryCoverage(BaseModel):
    """Whether every identity-bearing term of a request exists in the catalog.

    `confidence` is the field a consumer branches on:

    - `grounded`: every term either matched or is a recoverable misspelling.
      Retrieval and citation proceed normally.
    - `unanchored`: at least one term named something the catalog does not
      carry. Results are still returned, and still ordered, but they answer a
      narrower question than the one asked. Synthesis must not present them as
      the answer of record.
    - `unavailable`: the corpus vocabulary has not been built, so no verdict was
      reached. Consumers must behave exactly as they did before this module
      existed. An unseeded vocabulary makes every term look absent, and treating
      that as `unanchored` would refuse every request on the deployment.
    """

    confidence: CoverageConfidence
    unmatched_terms: list[str] = Field(default_factory=list)
    terms: list[TermCoverage] = Field(default_factory=list)
    note: str = ""

    @property
    def is_anchored(self) -> bool:
        """False only when a term named something the catalog does not carry."""
        return self.confidence != "unanchored"


#: Shown to a shopper above results. Names the terms rather than the mechanism,
#: matching how the Playground reports every other retrieval fact.
def unanchored_note(unmatched_terms: Sequence[str]) -> str:
    """Plain-language statement of what the catalog did not match."""
    if not unmatched_terms:
        return ""
    quoted = ", ".join(f"'{term}'" for term in unmatched_terms)
    subject = "term" if len(unmatched_terms) == 1 else "terms"
    return (
        f"Nothing in the catalog matches the {subject} {quoted}. "
        "The results below answer the rest of the request."
    )


def summarize(terms: Sequence[TermCoverage]) -> QueryCoverage:
    """Reduce per-term verdicts to one decision.

    Pure: every branch is exercised without a database. `unavailable` is not
    decided here, because an empty term list is indistinguishable from an
    unseeded vocabulary at this level; `assess` establishes that first.
    """
    unmatched = [term.token for term in terms if term.verdict == UNMATCHED_ANCHOR]
    if unmatched:
        return QueryCoverage(
            confidence="unanchored",
            unmatched_terms=unmatched,
            terms=list(terms),
            note=unanchored_note(unmatched),
        )
    return QueryCoverage(confidence="grounded", terms=list(terms))


def _vocabulary_ready(connection) -> bool:
    """Whether `refresh_corpus_lexeme()` has run against this database."""
    row = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM mosaic_search.corpus_lexeme) AS ready"
    ).fetchone()
    return bool(row and row["ready"])


def _unavailable(reason: str) -> QueryCoverage:
    return QueryCoverage(confidence="unavailable", note=reason)


def assess(query: str, *, word_similarity_floor: float | None = None) -> QueryCoverage:
    """Classify one request against the catalog vocabulary.

    Args:
        query: The shopper's request, exactly as submitted.
        word_similarity_floor: Override the trigram floor separating a
            misspelling from an absence for word-shaped tokens. Defaults to the
            SQL function's own default, which is unmeasured and documented as
            such in `db/sql/20_query_coverage.sql`.

    Returns:
        A `QueryCoverage`. Never raises for an unseeded vocabulary or a blank
        request; both yield `unavailable` or `grounded` respectively, so a
        caller can attach this to a response without a guard.
    """
    if not query or not query.strip():
        return QueryCoverage(confidence="grounded")
    with connect() as connection:
        if not _vocabulary_ready(connection):
            return _unavailable(
                "Corpus vocabulary is empty; run "
                "CALL mosaic_search.refresh_corpus_lexeme() to enable coverage."
            )
        if word_similarity_floor is None:
            rows = connection.execute(
                "SELECT * FROM mosaic_search.query_term_coverage(%s)",
                (query,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM mosaic_search.query_term_coverage(%s, %s)",
                (query, word_similarity_floor),
            ).fetchall()
    return summarize([TermCoverage(**row) for row in rows])
