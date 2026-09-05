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
absence, and `coverage.similarity_floor` in `db/config/retrieval.yaml` for the
measured number that separates them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

import psycopg

from scripts.retrieval_profile import load_profile
from service.db import connect
from service.models import QueryCoverage, TermCoverage

#: A term matching nothing, which nothing can recover. The request names
#: something outside the catalog.
UNMATCHED_ANCHOR = "unmatched_anchor"

#: A term matching nothing exactly, but close enough to a catalog term for the
#: trigram arm to reach it. Lab 1's `noice cancelng hedfones` is entirely this.
RECOVERABLE = "recoverable"

MATCHED = "matched"
IGNORED = "ignored"


def _quoted(unmatched_terms: Sequence[str]) -> str:
    return ", ".join(f"'{term}'" for term in unmatched_terms)


def _absence_sentence(unmatched_terms: Sequence[str]) -> str:
    """The one fact every surface states, worded once rather than copied.

    Shop and the agent disagree about what follows this sentence, never about
    the sentence itself. Two copies of it would let them drift into naming the
    same absence two ways.
    """
    subject = "term" if len(unmatched_terms) == 1 else "terms"
    return f"Nothing in the catalog matches the {subject} {_quoted(unmatched_terms)}."


#: Shown to a shopper above results. Names the terms rather than the mechanism,
#: matching how the Playground reports every other retrieval fact.
def unanchored_note(unmatched_terms: Sequence[str]) -> str:
    """Plain-language statement of what the catalog did not match."""
    if not unmatched_terms:
        return ""
    return (
        f"{_absence_sentence(unmatched_terms)} "
        "The results below answer the rest of the request."
    )


def decline_note(unmatched_terms: Sequence[str]) -> str:
    """The agent's answer of record when it may not recommend.

    Shop labels an unanchored result set and still shows it, because a shopper
    reading a caveat above real products is better served than one reading an
    empty page. The agent has no equivalent: its output is a single answer of
    record, so the absence Shop annotates is here a refusal to recommend.
    """
    if not unmatched_terms:
        return ""
    return (
        f"{_absence_sentence(unmatched_terms)} "
        "No product is recommended for this request."
    )


def decline_reason(unmatched_terms: Sequence[str]) -> str:
    """Why a run declined, in a form a client can branch on without prose.

    The prefix is stable and the terms follow it, so a caller can test for the
    verdict and still read the offending values.
    """
    if not unmatched_terms:
        return ""
    return f"unanchored_query_terms: {_quoted(unmatched_terms)}"


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
    """Whether `refresh_corpus_lexeme()` has run against this database.

    Both tables, not one. They answer different halves of the verdict --
    `corpus_lexeme` decides `matched`, `corpus_surface_lexeme` decides whether a
    term that matched nothing is recoverable -- so a database holding only the
    first would call every misspelling an absence and refuse the Lab 1 anchor.
    A half-seeded vocabulary is not a working guardrail; it is the outage the
    `unavailable` verdict exists to prevent.
    """
    row = connection.execute(
        """
        SELECT EXISTS (SELECT 1 FROM mosaic_search.corpus_lexeme)
           AND EXISTS (SELECT 1 FROM mosaic_search.corpus_surface_lexeme)
               AS ready
        """
    ).fetchone()
    return bool(row and row["ready"])


def _unavailable(reason: str) -> QueryCoverage:
    return QueryCoverage(confidence="unavailable", note=reason)


def assess(
    query: str,
    *,
    connection_factory: Callable[[], AbstractContextManager] | None = None,
    similarity_floor: float | None = None,
) -> QueryCoverage:
    """Classify one request against the catalog vocabulary.

    Args:
        query: The shopper's request, exactly as submitted.
        connection_factory: Where to get a connection. Defaults to the shared
            pool. `RetrievalService` passes its own injected factory so coverage
            reaches the same database the search did, and so a test that
            substitutes a connection does not fall through to the real pool.
            The caller must not already hold a checkout from the same pool;
            `service.db.connect` documents why nesting is unsafe.
        similarity_floor: Override the trigram floor separating a misspelling
            from an absence for word-shaped tokens. Defaults to
            `coverage.similarity_floor` in `db/config/retrieval.yaml`, which is
            always passed explicitly rather than left to the SQL default: the
            two agree today, and `scripts/config_tripwire.py` keeps them
            agreeing, but a request that reads the number the yaml declares
            cannot be told apart from one that reads a stale copy on the
            cluster unless it sends the value.

    Returns:
        A `QueryCoverage`. Never raises for an unseeded vocabulary, an
        uninstalled function, or a blank request, so a caller can attach this
        to a response without a guard.
    """
    if not query or not query.strip():
        return QueryCoverage(confidence="grounded")
    factory = connection_factory or connect
    try:
        with factory() as connection:
            if not _vocabulary_ready(connection):
                return _unavailable(
                    "Corpus vocabulary is empty; run "
                    "CALL mosaic_search.refresh_corpus_lexeme() to enable coverage."
                )
            floor = (
                load_profile().coverage_similarity_floor
                if similarity_floor is None
                else similarity_floor
            )
            rows = connection.execute(
                "SELECT * FROM mosaic_search.query_term_coverage(%s, %s::real)",
                (query, floor),
            ).fetchall()
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction):
        # A cluster provisioned before db/sql/20_query_coverage.sql existed has
        # neither the vocabulary table nor the function. Coverage is an
        # enhancement to search, never a dependency of it: an unmigrated
        # database must keep serving, not 500 on every request.
        return _unavailable(
            "Query coverage is not installed on this database; run "
            "`make db-install` to add mosaic_search.query_term_coverage."
        )
    return summarize([TermCoverage(**row) for row in rows])
