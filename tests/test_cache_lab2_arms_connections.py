"""The Lab 2 cache shares its judged queries across connections without changing them."""

import base64
import struct
import threading

from scripts import cache_lab2_arms

VECTOR = base64.b64encode(struct.pack("<1024f", *([0.0] * 1024))).decode()


class FakeConnection:
    def __init__(self, opened: list):
        self.statements: list[str] = []
        self.rolled_back = False
        opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, *_):
        self.statements.append(statement)

    def rollback(self):
        self.rolled_back = True


def cases(count: int) -> list[dict]:
    return [
        {"query_id": 100 + index, "query": f"query {index}", "filters": {"n": index}}
        for index in range(count)
    ]


def test_every_query_is_cached_once_in_the_judged_order(monkeypatch):
    threads: set[int] = set()

    def lists(connection, query, filters, vector):
        threads.add(threading.get_ident())
        return {"fts": [[filters["n"], 1]], "fuzzy": [], "semantic": [[query, 2]]}

    monkeypatch.setattr(cache_lab2_arms, "search_lists", lists)
    opened: list[FakeConnection] = []
    judged = cases(11)
    vectors = {str(case["query_id"]): VECTOR for case in judged}

    shared = cache_lab2_arms.cache_queries(
        lambda: FakeConnection(opened), judged, vectors
    )
    alone = cache_lab2_arms.cache_queries(
        lambda: FakeConnection([]), judged, vectors, 1
    )

    assert list(shared) == [str(case["query_id"]) for case in judged]
    assert shared == alone
    assert len(opened) == cache_lab2_arms.CONNECTIONS
    assert all(c.statements[0] == "SET TRANSACTION READ ONLY" for c in opened)
    assert all(c.rolled_back for c in opened)


def test_fewer_queries_than_connections_opens_only_what_it_uses(monkeypatch):
    monkeypatch.setattr(cache_lab2_arms, "search_lists", lambda *_: {})
    opened: list[FakeConnection] = []
    judged = cases(2)

    cache_lab2_arms.cache_queries(
        lambda: FakeConnection(opened),
        judged,
        {str(c["query_id"]): VECTOR for c in judged},
    )

    assert len(opened) == 2
