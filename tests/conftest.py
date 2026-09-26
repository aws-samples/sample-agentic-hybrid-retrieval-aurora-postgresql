"""Collection-time hooks shared by the whole test suite."""

from __future__ import annotations

import os

# `service.config.get_settings()` fails closed when origin verification is
# required (the safe default) and no secret is configured, so it must find one
# before the first import that triggers it -- which happens as soon as any
# test module imports `service.main`, well before any fixture runs. This is a
# fixed, non-secret value for the offline suite only; nothing here reaches a
# real deployment, which gets its own value from `deploy/mosaic-bootstrap.sh`.
os.environ.setdefault("MOSAIC_ORIGIN_VERIFY_SECRET", "offline-test-suite-secret")

import pytest

from service.access_control import (
    reset_admission_state,
    verify_origin_access,
)
from service.config import get_settings
from service.main import app


@pytest.fixture(autouse=True)
def _reset_admission_state():
    """Give every test a fresh active-run and rate-limit budget.

    Both counters in `service.access_control` are module-level, process-wide
    state by design -- that is what makes them a real per-process quota rather
    than per-request bookkeeping. Left alone across hundreds of tests sharing
    one pytest process, an early test's search or agent calls would count
    against an unrelated, later test's rate-limit window.
    """
    reset_admission_state()
    yield
    reset_admission_state()


@pytest.fixture(autouse=True)
def _bypass_origin_verification():
    """Exercise application routes without the caller-trust boundary by default.

    `tests/test_access_control.py` is the dedicated suite for the real
    dependency: unauthorized, spoofed, and correctly authorized requests, and
    the loopback-only development bypass. Every other test in this repository
    is testing retrieval, agent, or catalog behavior, not this gate, so it runs
    with the gate overridden open -- the standard FastAPI pattern for a global
    auth dependency in tests -- rather than every call site in ~20 files
    carrying a header whose value means nothing to the test it is in.
    """
    app.dependency_overrides[verify_origin_access] = lambda: None
    yield
    app.dependency_overrides.pop(verify_origin_access, None)


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
