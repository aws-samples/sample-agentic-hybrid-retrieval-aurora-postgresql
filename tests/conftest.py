"""Collection-time hooks shared by the whole test suite."""

from __future__ import annotations

import pytest

from service.config import get_settings


@pytest.fixture(autouse=True)
def isolate_unit_catalog(request, monkeypatch):
    """Keep a participant's selected catalog out of historical unit-test doubles.

    Live tests retain the deployment selection. Unit tests that exercise a real
    catalog set it explicitly in their own fixture or test body.
    """
    if request.node.get_closest_marker("aurora") is None:
        monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)


_SKIP_REASON = (
    "Rule: aurora-marked tests require a live Aurora DSN because they exercise "
    "real retrieval and scope-enforcement SQL, not a stand-in. Value: skipping "
    "here keeps a plain `pytest` invocation correct in every environment "
    "instead of failing wherever no cluster is reachable. Fix: export "
    "DATABASE_URL in your shell, then run `make test` or pytest directly -- "
    "neither one loads it from .env for you."
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `aurora`-marked tests when no database DSN is configured.

    A pytest marker is only a label; it does not skip anything on its own. This
    hook supplies the missing skip decision, and it reads
    `service.config.get_settings().database_url` -- the same source of truth
    `service.db.connect()` uses -- so the skip decision can never disagree with
    what a real connection attempt would do.
    """
    if get_settings().database_url:
        return
    skip_aurora = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "aurora" in item.keywords:
            item.add_marker(skip_aurora)
