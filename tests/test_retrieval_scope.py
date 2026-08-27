"""Grant-scope declaration and enforcement."""

import pytest
from pydantic import ValidationError

from service.models import RetrievalProfile, SearchRequest


def test_authorized_limit_defaults_to_the_served_limit():
    request = SearchRequest(query="noise cancelling headphones", limit=12)

    assert request.authorized_limit == 12


def test_authorized_limit_may_be_narrower_than_the_served_limit():
    request = SearchRequest(
        query="noise cancelling headphones", limit=50, authorized_limit=2
    )

    assert request.authorized_limit == 2


def test_authorized_limit_may_not_exceed_the_served_limit():
    with pytest.raises(ValidationError, match="authorized_limit"):
        SearchRequest(
            query="noise cancelling headphones", limit=12, authorized_limit=13
        )


def test_authorized_limit_may_not_be_zero():
    with pytest.raises(ValidationError):
        SearchRequest(query="noise cancelling headphones", limit=12, authorized_limit=0)


def test_profile_authorized_limit_is_absent_until_declared():
    assert RetrievalProfile().authorized_limit is None


from contextlib import contextmanager
from uuid import UUID, uuid4

SCOPE_ID = UUID("11111111-2222-3333-4444-555555555555")


class _Result:
    def __init__(self, one):
        self._one = one

    def fetchone(self):
        return self._one


def _fake_connect(captured, row):
    class Connection:
        def execute(self, sql, parameters):
            captured["sql"] = sql
            captured["parameters"] = parameters
            return _Result(row)

    @contextmanager
    def connect():
        yield Connection()

    return connect


def test_authorized_products_pass(monkeypatch):
    from service import retrieval_scope

    captured = {}
    monkeypatch.setattr(
        retrieval_scope,
        "connect",
        _fake_connect(captured, {"authorized_limit": 3, "out_of_scope": []}),
    )

    retrieval_scope.assert_products_in_retrieval_scope(SCOPE_ID, [101, 102])

    assert captured["parameters"]["scope_id"] == SCOPE_ID
    assert captured["parameters"]["product_ids"] == [101, 102]


def test_product_outside_the_window_is_refused(monkeypatch):
    from service import retrieval_scope

    monkeypatch.setattr(
        retrieval_scope,
        "connect",
        _fake_connect({}, {"authorized_limit": 3, "out_of_scope": [412]}),
    )

    with pytest.raises(retrieval_scope.ScopeViolation) as error:
        retrieval_scope.assert_products_in_retrieval_scope(SCOPE_ID, [101, 412])

    detail = error.value.detail
    assert "412" in detail
    assert "3" in detail
    assert "fix:" in detail


def test_event_without_authorized_limit_fails_closed(monkeypatch):
    """A legacy event recorded result_limit 50 while granting 1. Never infer."""
    from service import retrieval_scope

    monkeypatch.setattr(
        retrieval_scope,
        "connect",
        _fake_connect({}, {"authorized_limit": None, "out_of_scope": [101]}),
    )

    with pytest.raises(retrieval_scope.ScopeViolation) as error:
        retrieval_scope.assert_products_in_retrieval_scope(SCOPE_ID, [101])

    detail = error.value.detail
    assert "authorized_limit" in detail
    assert "fix:" in detail
    assert "result_limit" not in detail


def test_unknown_scope_fails_closed(monkeypatch):
    from service import retrieval_scope

    monkeypatch.setattr(
        retrieval_scope,
        "connect",
        _fake_connect({}, {"authorized_limit": None, "out_of_scope": [101]}),
    )

    with pytest.raises(retrieval_scope.ScopeViolation):
        retrieval_scope.assert_products_in_retrieval_scope(uuid4(), [101])


def test_empty_product_list_needs_no_query(monkeypatch):
    """Nothing requested is nothing to authorize, and it must not fail closed."""
    from service import retrieval_scope

    def explode():
        raise AssertionError("the guard queried the database for zero products")

    monkeypatch.setattr(retrieval_scope, "connect", explode)

    retrieval_scope.assert_products_in_retrieval_scope(SCOPE_ID, [])


def test_generic_detail_discloses_nothing():
    from service import retrieval_scope

    assert "product" in retrieval_scope.SCOPE_DENIED_DETAIL.lower()
    assert "search_event_id" in retrieval_scope.SCOPE_DENIED_DETAIL


@pytest.mark.aurora
def test_pool_members_outside_the_window_are_refused_live():
    """The measured fail-open: 50 candidates persist, far fewer are granted.

    Falsifier: if the guard authorized any candidate merely present in
    `search_result_event`, this passes a product the caller never received.
    """
    from service.models import SearchRequest
    from service.retrieval import get_retrieval_service
    from service.retrieval_scope import (
        ScopeViolation,
        assert_products_in_retrieval_scope,
    )

    response = get_retrieval_service().search(
        SearchRequest(query="noise cancelling headphones", limit=12, authorized_limit=2)
    )
    granted = [product.product_id for product in response.results[:2]]
    withheld = [product.product_id for product in response.results[2:5]]
    assert withheld, "the fused pool returned fewer than three candidates"

    assert_products_in_retrieval_scope(response.search_event_id, granted)

    with pytest.raises(ScopeViolation):
        assert_products_in_retrieval_scope(response.search_event_id, withheld)


def test_aurora_marker_is_registered_in_pyproject():
    """Pin the `aurora` marker's registration in pyproject.toml.

    This is unrelated to what makes `tests/conftest.py`'s skip hook work: that
    hook matches on the literal string "aurora" in `item.keywords`, which
    comes straight from the `@pytest.mark.aurora` decorator and does not read
    this registry entry at all (see
    `test_conftest_skip_hook_matches_the_aurora_marker_name` for the seam that
    actually protects the hook). There is no `--strict-markers` or
    `filterwarnings` configured in this repo, so dropping or renaming this
    entry would not break the skip -- it would only make `pytest --markers`
    stop documenting the marker and make every `@pytest.mark.aurora` use emit
    an unregistered-marker warning. Pin registry hygiene, not hook behavior.
    """
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject_path.read_text())

    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.strip().startswith("aurora:") for marker in markers)


def test_conftest_skip_hook_matches_the_aurora_marker_name():
    """Pin the seam that actually protects the skip hook: the marker name.

    `tests/conftest.py` decides whether to skip by checking `"aurora" in
    item.keywords` -- a literal string, independent of the pyproject.toml
    registry entry above. The only thing that keeps that literal meaningful
    is that it names the same marker used to decorate
    `test_pool_members_outside_the_window_are_refused_live` below. Read the
    literal straight out of conftest.py's source and cross-check it against
    that test's actual marker, so renaming either side alone fails loudly
    instead of silently stopping the skip from ever matching.
    """
    import re
    from pathlib import Path

    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    conftest_source = conftest_path.read_text()

    match = re.search(r'if\s+"([^"]+)"\s+in\s+item\.keywords:', conftest_source)
    assert match, "could not find the marker literal the skip hook matches on"
    matched_literal = match.group(1)

    marker_names = {
        marker.name
        for marker in test_pool_members_outside_the_window_are_refused_live.pytestmark
    }
    assert matched_literal in marker_names, (
        f"conftest.py's skip hook matches on {matched_literal!r}, but "
        f"test_pool_members_outside_the_window_are_refused_live is decorated "
        f"with {marker_names!r} -- renaming one without the other silently "
        "breaks the skip"
    )
    assert matched_literal == "aurora"


def test_aurora_release_ci_requires_database_url_before_running_tests():
    """The conftest skip is only safe because `aurora-release` fails fast.

    Rule: a test that silently skips can hide a broken security guard, so a
    green offline run is not evidence the guard still works. Value: this skip
    is safe only because `aurora-release` in ci.yml hard-requires DATABASE_URL
    before it ever reaches `make test`, so the skip can never silently apply
    in the one job that exists to run these tests. That precondition has two
    parts: the check must run before the test step, and it must actually stop
    the job on failure -- a `test -n ...` left unguarded by a nonzero `exit`
    would let the job fall through to `make test` with an empty DSN, every
    Aurora test would then silently skip, and CI would stay green with no
    real SQL coverage. Fix: if either part is ever removed, this assertion is
    what catches it.
    """
    import re
    from pathlib import Path

    workflow_path = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    )
    workflow_text = workflow_path.read_text()

    after_job_name = workflow_text.split("aurora-release:", 1)[1]
    next_job_boundary = re.search(r"\n  [A-Za-z_][\w-]*:[ \t]*\n", after_job_name)
    release_job = (
        after_job_name[: next_job_boundary.start()]
        if next_job_boundary
        else after_job_name
    )

    guard = 'test -n "$DATABASE_URL"'
    test_step = "Run the Python test suite against Aurora"

    guard_index = release_job.find(guard)
    test_step_index = release_job.find(test_step)

    assert guard_index != -1, "aurora-release no longer guards on DATABASE_URL"
    assert test_step_index != -1, "aurora-release no longer runs its test step"
    assert guard_index < test_step_index, "the DATABASE_URL guard runs too late"

    guard_block_end = release_job.find("}", guard_index)
    assert guard_block_end != -1, "the DATABASE_URL guard's `{ ... }` never closes"
    guard_block = release_job[guard_index:guard_block_end]
    assert re.search(r"\bexit\s+[1-9]\d*\b", guard_block), (
        "the DATABASE_URL guard no longer forces a nonzero exit; a bare "
        "`test -n ...` without `exit 2` lets the job fall through to "
        "`make test` with an empty DSN"
    )


def _evidence_record():
    from service.models import EvidenceRecord

    return EvidenceRecord(
        evidence_id=9001,
        product_id=101,
        evidence_type="product_spec",
        source_name="Mosaic catalog specification",
        source_uri="mosaic://evidence/product-spec/101",
        revision="r1",
        title="Battery life",
        text="Rated for 30 hours with adaptive noise cancelling on.",
        rating=None,
        is_verified=True,
    )


def test_evidence_route_requires_a_retrieval_scope():
    from fastapi.testclient import TestClient

    from service.main import app

    response = TestClient(app).post(
        "/api/products/101/evidence",
        json={"evidence_query": "How long does the battery last?"},
    )

    assert response.status_code == 422
    assert "retrieval_scope_id" in response.text


def test_evidence_route_serves_a_granted_product(monkeypatch):
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app

    class FakeRetrieval:
        def embed_query(self, _query):
            return [0.125, 0.25]

    monkeypatch.setattr(main, "get_retrieval_service", lambda: FakeRetrieval())
    monkeypatch.setattr(
        main,
        "get_product_evidence_records",
        lambda product_id, query, embedding, *, limit: [_evidence_record()],
    )
    monkeypatch.setattr(
        main, "assert_products_in_retrieval_scope", lambda scope, products: None
    )

    response = TestClient(app).post(
        "/api/products/101/evidence",
        json={
            "retrieval_scope_id": str(SCOPE_ID),
            "evidence_query": "How long does the battery last?",
        },
    )

    assert response.status_code == 200
    assert response.json()["evidence"][0]["evidence_id"] == 9001


def test_evidence_route_refuses_an_ungranted_product_with_404(monkeypatch):
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app
    from service.retrieval_scope import SCOPE_DENIED_DETAIL, ScopeViolation

    def refuse(_scope, _products):
        raise ScopeViolation(
            "FAIL retrieval scope 1111 products [412]: found products outside "
            "the authorized window of 3; fix: use a product from the first 3."
        )

    monkeypatch.setattr(main, "assert_products_in_retrieval_scope", refuse)

    def unreachable(*_args, **_kwargs):
        raise AssertionError("evidence was retrieved before the scope check")

    monkeypatch.setattr(main, "get_retrieval_service", unreachable)

    response = TestClient(app).post(
        "/api/products/412/evidence",
        json={
            "retrieval_scope_id": str(SCOPE_ID),
            "evidence_query": "How long does the battery last?",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == SCOPE_DENIED_DETAIL


def test_evidence_404_body_discloses_neither_products_nor_window(monkeypatch):
    """The rich message is a server-side diagnostic, never a response body."""
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app
    from service.retrieval_scope import SCOPE_DENIED_DETAIL, ScopeViolation

    def refuse(_scope, _products):
        raise ScopeViolation(
            "FAIL retrieval scope 1111 products [412]: found products outside "
            "the authorized window of 37; fix: use one of the first 37."
        )

    monkeypatch.setattr(main, "assert_products_in_retrieval_scope", refuse)

    response = TestClient(app).post(
        "/api/products/412/evidence",
        json={
            "retrieval_scope_id": str(SCOPE_ID),
            "evidence_query": "How long does the battery last?",
        },
    )
    body = response.text

    assert response.status_code == 404
    assert response.json()["detail"] == SCOPE_DENIED_DETAIL
    assert "412" not in body
    assert "37" not in body
    assert "authorized window" not in body


def _receipt_row(product_id=101, result_rank=1, fused_rank=7):
    return {
        "product_id": product_id,
        "result_rank": result_rank,
        "fts_rank": 2,
        "trigram_rank": None,
        "semantic_rank": 1,
        "fused_rank": fused_rank,
        "rerank_rank": 1,
        "scores": {
            "fts": 0.4,
            "trigram": None,
            "semantic": 0.8,
            "rrf": 0.03,
            "pre_rerank": 0.03,
            "rerank": 0.91,
            "exact_sku_match": False,
        },
        "provenance": {
            "channels": {
                "fts": {"rrf_contribution": 0.01},
                "vector": {"rrf_contribution": 0.02},
            }
        },
    }


def test_signals_from_receipt_is_public_on_retrieval():
    """The projection lives with receipts, not with the authorization guard."""
    from service import retrieval, retrieval_scope

    # result_rank and fused_rank must differ: they are different rank spaces
    # (returned-row vs. full-pool). Equal values would let a mapping swap
    # between final_rank and pre_rerank_rank pass silently -- do not "tidy"
    # these back to being equal.
    row = _receipt_row(result_rank=1, fused_rank=7)
    signals = retrieval.signals_from_receipt(row)

    assert signals.fts.rank == 2
    assert signals.fts.rrf_contribution == 0.01
    assert signals.semantic.rrf_contribution == 0.02
    assert signals.final_rank == row["result_rank"]
    assert signals.pre_rerank_rank == row["fused_rank"]
    assert not hasattr(retrieval_scope, "signals_from_receipt")


def test_retrieval_scope_exposes_exactly_one_public_primitive():
    """Cohesion rule: the guard module must not become a junk drawer.

    Asserts on what the module *defines*, filtered by `__module__`, rather than on
    everything in its namespace. Listing imports here would make the test fail on
    an unrelated refactor while still passing if a second primitive were added,
    which is backwards.

    Falsifier: add any second public function or class to
    `service/retrieval_scope.py` and this fails.
    """
    import inspect

    from service import retrieval_scope

    defined_here = {
        name
        for name, value in vars(retrieval_scope).items()
        if not name.startswith("_")
        and (inspect.isfunction(value) or inspect.isclass(value))
        and getattr(value, "__module__", None) == "service.retrieval_scope"
    }

    assert defined_here == {
        "ScopeViolation",
        "assert_products_in_retrieval_scope",
    }
    assert retrieval_scope.__all__ == [
        "SCOPE_DENIED_DETAIL",
        "ScopeViolation",
        "assert_products_in_retrieval_scope",
    ]


def test_compare_route_refuses_an_ungranted_product_with_404(monkeypatch):
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app
    from service.retrieval_scope import SCOPE_DENIED_DETAIL, ScopeViolation

    def refuse(_scope, _products):
        raise ScopeViolation("FAIL retrieval scope products [412]: window 3")

    monkeypatch.setattr(main, "assert_products_in_retrieval_scope", refuse)

    response = TestClient(app).post(
        f"/api/retrieval/events/{SCOPE_ID}/compare",
        json={"product_ids": [101, 412]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == SCOPE_DENIED_DETAIL


def test_compare_route_needs_two_to_five_distinct_products():
    from fastapi.testclient import TestClient

    from service.main import app

    client = TestClient(app)

    assert (
        client.post(
            f"/api/retrieval/events/{SCOPE_ID}/compare",
            json={"product_ids": [101]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/retrieval/events/{SCOPE_ID}/compare",
            json={"product_ids": [1, 2, 3, 4, 5, 6]},
        ).status_code
        == 422
    )


def test_compare_route_rejects_duplicates_collapsed_below_the_minimum(monkeypatch):
    """Duplicates must be collapsed before the count is judged, not after.

    `[101, 101]` has raw length 2, so it clears Pydantic's `min_length=2` on
    `product_ids`. The route's manual check in `service/main.py` must still
    reject it once `dict.fromkeys` collapses it to a single distinct product.
    Asserting on the body (a plain string `detail`), not just the status code,
    is what distinguishes this rejection from Pydantic's `min_length` failure,
    which produces a list-shaped `detail` instead.
    """
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app

    def unreachable(*_args, **_kwargs):
        raise AssertionError("the distinct-count check let a duplicate through")

    monkeypatch.setattr(main, "assert_products_in_retrieval_scope", unreachable)

    response = TestClient(app).post(
        f"/api/retrieval/events/{SCOPE_ID}/compare",
        json={"product_ids": [101, 101]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str), "Pydantic's own 422 detail is a list, not a string"
    assert "found 1" in detail
    assert "distinct products" in detail


def test_compare_route_accepts_duplicates_that_collapse_within_bounds(monkeypatch):
    """The accept-side mirror: collapsing duplicates must not over-reject either.

    `[1, 2, 3, 4, 1]` has raw length 5 (inside Pydantic's `max_length=5`) and
    collapses to four distinct products (inside the manual check's [2, 5]
    range too). This proves the manual check judges the *distinct* count, not
    the raw one, without a live database or fully mocked product hydration:
    patch `assert_products_in_retrieval_scope` to raise, and confirm the
    response is the scope-check's 404 (not the distinct-count check's 422),
    with the deduplicated id list the distinct-count check actually passed on.

    Note: the literal "six collapsing to five" mirror from the review is not
    reachable through this route at all. Pydantic's `max_length=5` on
    `product_ids` validates the *raw* list before the route body ever runs,
    and `dict.fromkeys` only ever shrinks a count, never grows it, so any body
    Pydantic admits already has a distinct count at or below 5. The manual
    check's upper-bound arm can never fire; only its lower-bound arm (this
    test's sibling above) is reachable.
    """
    from fastapi.testclient import TestClient

    from service import main
    from service.main import app
    from service.retrieval_scope import ScopeViolation

    def refuse(_scope, product_ids):
        assert product_ids == [1, 2, 3, 4]
        raise ScopeViolation("FAIL retrieval scope products [1]: window 3")

    monkeypatch.setattr(main, "assert_products_in_retrieval_scope", refuse)

    response = TestClient(app).post(
        f"/api/retrieval/events/{SCOPE_ID}/compare",
        json={"product_ids": [1, 2, 3, 4, 1]},
    )

    assert response.status_code == 404


def test_agent_declares_the_window_it_grants_not_the_one_it_requests(monkeypatch):
    """The agent asks for 50 to inspect the pool and grants at most 2.

    Falsifier: if the tool passed no `authorized_limit`, the request would
    declare 50, and every one of the 50 pooled candidates would become
    evidence-addressable while the model only ever saw 2.
    """
    from service import agent_tools
    from service.models import (
        RetrievalDiagnostics,
        RetrievalProfile,
        SearchFilters,
        SearchResponse,
    )

    captured = {}

    def _product(product_id):
        from service.models import ProductSummary, SourceAttribution

        return ProductSummary(
            product_id=product_id,
            sku=f"SKU-{product_id}",
            title=f"Product {product_id}",
            short_description="A product.",
            domain="consumer_electronics",
            category_key="over-ear-headphones",
            category_path="Electronics",
            brand="Brand",
            model=f"M{product_id}",
            price_cents=19900,
            list_price_cents=19900,
            review_count=10,
            availability="in_stock",
            inventory_count=5,
            attributes={},
            tags=[],
            sources=[
                SourceAttribution(
                    source_uri=f"https://example.test/{product_id}",
                    revision="1",
                    title=f"Product {product_id}",
                    quote="A product.",
                )
            ],
        )

    class FakeRetrieval:
        def search(self, request):
            captured["limit"] = request.limit
            captured["authorized_limit"] = request.authorized_limit
            return SearchResponse(
                search_event_id=SCOPE_ID,
                query=request.query,
                normalized_query=request.query,
                applied_filters={},
                results=[_product(100 + index) for index in range(50)],
                diagnostics=RetrievalDiagnostics(
                    strategy="rrf_fusion+rerank+exact_sku_preservation",
                    embedding_model_id="fake",
                    embedding_dimensions=1024,
                    rerank_model_id="fake",
                    rerank_status="applied",
                    ranking_policy=["RRF candidate fusion"],
                    retrieval_profile=RetrievalProfile(),
                    candidate_counts={"fused_pool": 50},
                    stage_timings_ms={},
                    total_latency_ms=1,
                    warnings=[],
                ),
            )

    monkeypatch.setattr(agent_tools, "get_retrieval_service", lambda: FakeRetrieval())
    state = {
        "base_filters": SearchFilters(),
        "result_limit": 2,
        "searches": [],
        "search_event_ids": [],
        "context_product_ids": [],
        "products": {},
        "evidence": {},
        "evidence_by_product": {},
        "trace": [],
        "execution_path": "full_retrieval",
    }
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.search_products("noise cancelling headphones", limit=2)
    finally:
        agent_tools._RUN.reset(token)

    assert result["ok"] is True
    assert captured["limit"] == 50, "the agent still inspects the full pool"
    assert captured["authorized_limit"] == 2, "but it grants only what it returns"
    assert len(state["products"]) == captured["authorized_limit"]


@pytest.mark.aurora
def test_service_scope_equals_run_scope_on_the_agent_path():
    """The two authorities must not disagree about what was granted.

    Falsifier: drop `authorized_limit` from the tool's SearchRequest and the
    service authorizes all 50 pooled candidates while `_RUN` registers 2.
    """
    from service import agent_tools
    from service.models import SearchFilters
    from service.retrieval_scope import (
        ScopeViolation,
        assert_products_in_retrieval_scope,
    )

    state = agent_tools.start_run(
        "noise cancelling headphones under $300",
        SearchFilters(),
        result_limit=2,
    )
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.search_products(
            "noise cancelling headphones under $300", limit=2
        )
        assert result["ok"] is True, result
        scope = state["search_event_ids"][0]
        registered = sorted(state["products"])

        assert_products_in_retrieval_scope(scope, registered)

        ungranted = [
            product["product_id"]
            for product in result["products"]
            if product["product_id"] not in state["products"]
        ]
        for product_id in ungranted:
            with pytest.raises(ScopeViolation):
                assert_products_in_retrieval_scope(scope, [product_id])
    finally:
        agent_tools._RUN.reset(token)
