"""The single authority for retrieved-product grant scope.

A retrieval receipt records what happened. `authorized_limit` is what the caller
declared it was granting. This module is the only place that decides whether a
product falls inside a retrieval's grant, so HTTP, MCP, and the skill surface
cannot drift into three interpretations of the same rule.

It deliberately does not own citation authorization. That stays turn-local in
`service.agent_tools`, because retrieving scoped evidence does not by itself
authorize that evidence for synthesis, and collapsing the two would erase the
distinction Lab 3 teaches.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from service.db import connect

#: This module owns exactly one rule, so it exports exactly one primitive and its
#: exception. A second entry here means the thing being added belongs in
#: `service/retrieval.py` instead. A test asserts this list.
__all__ = [
    "SCOPE_DENIED_DETAIL",
    "ScopeViolation",
    "assert_products_in_retrieval_scope",
]

#: The only thing an out-of-scope caller is told. It names no product, no rank,
#: and no window, and it is identical for an unknown scope and a refused
#: product, so a refusal cannot be used to probe what exists.
SCOPE_DENIED_DETAIL = (
    "That product is not granted by the supplied retrieval scope. Run a new "
    "search and use the search_event_id it returns."
)

_SCOPE_SQL = """
WITH scope AS (
    SELECT (retrieval_profile->>'authorized_limit')::int AS authorized_limit
    FROM mosaic.search_event
    WHERE search_event_id = %(scope_id)s
      AND retrieval_profile ? 'authorized_limit'
)
SELECT
    (SELECT authorized_limit FROM scope) AS authorized_limit,
    coalesce(
        array_agg(requested.product_id ORDER BY requested.product_id),
        '{}'::bigint[]
    ) AS out_of_scope
FROM unnest(%(product_ids)s::bigint[]) AS requested(product_id)
WHERE NOT EXISTS (
    SELECT 1
    FROM mosaic.search_result_event AS receipt, scope
    WHERE receipt.search_event_id = %(scope_id)s
      AND receipt.product_id = requested.product_id
      AND receipt.result_rank <= scope.authorized_limit
)
"""


class ScopeViolation(RuntimeError):
    """A caller asked for a product its retrieval scope did not grant."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def assert_products_in_retrieval_scope(
    retrieval_scope_id: UUID,
    product_ids: Sequence[int],
) -> None:
    """Raise unless every product was granted by that retrieval.

    Fail-closed is structural rather than a branch. A missing event, or an event
    whose profile carries no `authorized_limit`, leaves the `scope` CTE empty, so
    the `NOT EXISTS` holds for every requested product and all of them are
    refused. There is no fallback to `result_limit`: the agent path recorded 50
    while granting 1 or 2, so inferring a window from a legacy receipt would
    recreate the fail-open this guard exists to close.

    Args:
        retrieval_scope_id: A `search_event_id` returned by a search.
        product_ids: The products the caller wants to act on.

    Raises:
        ScopeViolation: With a `detail` naming the rule, the offending products,
            and the nearest fix. Callers crossing an HTTP boundary must answer
            with `SCOPE_DENIED_DETAIL` instead of this message.
    """
    requested = list(dict.fromkeys(product_ids))
    if not requested:
        return
    with connect() as connection:
        row = connection.execute(
            _SCOPE_SQL,
            {"scope_id": retrieval_scope_id, "product_ids": requested},
        ).fetchone()

    out_of_scope = list(row["out_of_scope"] or [])
    if not out_of_scope:
        return

    authorized_limit = row["authorized_limit"]
    if authorized_limit is None:
        raise ScopeViolation(
            f"FAIL retrieval scope {retrieval_scope_id}: found no "
            "authorized_limit on that retrieval event, so it does not exist or "
            "predates explicit authorization; fix: run a new search and use the "
            "search_event_id it returns."
        )
    raise ScopeViolation(
        f"FAIL retrieval scope {retrieval_scope_id} products {out_of_scope}: "
        f"found products outside the authorized window of {authorized_limit}; "
        f"fix: use a product from the first {authorized_limit} result(s) of "
        "that retrieval, or run a new search declaring a wider "
        "authorized_limit."
    )
