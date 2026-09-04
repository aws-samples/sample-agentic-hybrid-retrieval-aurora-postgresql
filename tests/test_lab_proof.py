"""Lab state and completion proof: the three proofs house rule 7 requires.

1. Red at birth -- `set_isolated_lab_state` on a copy of the two seam files
   makes the proof report `source_state == "broken"`.
2. Independence -- editing an unrelated service file in that same copy leaves
   `source_state` alone.
3. Witness -- the literal check counts each lab ships, so a proof that silently
   stopped evaluating a lab cannot read green.

Aurora is not reachable from a plain test run, so the database reads are driven
by a fake connection that answers the real queries. The retrieval path is the
production `service.telemetry.search_with_telemetry` seam, substituted with a
canned `SearchResponse` rather than reimplemented.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from uuid import UUID, uuid4

import pytest

from scripts.lab_state import (
    LABS,
    REPO,
    lab_is_solved,
    set_isolated_lab_state,
)
from service import lab_proof
from service.models import (
    ProductSummary,
    RankSignal,
    ResultSignals,
    RetrievalDiagnostics,
    RetrievalProfile,
    SearchResponse,
)

INDEPENDENT_FILE = "service/catalog.py"
AGENT_RUN_ID = UUID("5e0c2b9a-1f2d-4c3b-8a7e-0d1c2b3a4f56")
SESSION_ID = UUID("11111111-2222-3333-4444-555555555555")

SOLVED_LAB_1_DEFINITION = """
    CREATE FUNCTION mosaic_search.search_hybrid_rrf(...) AS $$
    WITH typo AS (SELECT * FROM mosaic_search.search_trigram(q, f, l, t))
    SELECT product_id FROM typo
    $$
"""
BROKEN_LAB_1_DEFINITION = """
    CREATE FUNCTION mosaic_search.search_hybrid_rrf(...) AS $$
    SELECT product_id FROM fts
    $$
"""


@pytest.fixture
def lab_repo(tmp_path: Path) -> Path:
    """A copy of both lab seam files plus one file no lab owns."""
    relative_paths = {definition[0] for definition in LABS.values()}
    for relative_path in relative_paths | {INDEPENDENT_FILE}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """Answers the real Aurora queries `lab_proof` issues, by SQL shape."""

    def __init__(
        self,
        *,
        lab_1_definition: str = SOLVED_LAB_1_DEFINITION,
        rrf_correct: bool = True,
        turn: dict | None = None,
        searches: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> None:
        self.lab_1_definition = lab_1_definition
        self.rrf_correct = rrf_correct
        self.turn = turn
        self.searches = searches or []
        self.tools = tools or []
        self.statements: list[str] = []

    def execute(self, sql: str, params=None) -> _FakeCursor:
        self.statements.append(sql)
        if "pg_get_functiondef" in sql:
            return _FakeCursor([{"definition": self.lab_1_definition}])
        if "reciprocal_rank_contribution" in sql:
            rrf_k = RetrievalProfile().rrf_k
            first = 1.0 / (rrf_k + 1)
            # The broken lab ties every source position at 1 / (k + 1).
            second = 1.0 / (rrf_k + 2) if self.rrf_correct else first
            return _FakeCursor(
                [{"first_contribution": first, "second_contribution": second}]
            )
        if "mosaic.search_result_event" in sql:
            return _FakeCursor([])
        if "mosaic.agent_turn" in sql and "agent_tool_event" not in sql:
            return _FakeCursor([self.turn] if self.turn else [])
        if "mosaic.search_event" in sql:
            return _FakeCursor(self.searches)
        if "mosaic.agent_tool_event" in sql:
            return _FakeCursor(self.tools)
        raise AssertionError(f"unexpected statement: {sql}")


@contextmanager
def _connection(connection: _FakeConnection):
    yield connection


def _use(monkeypatch, connection: _FakeConnection) -> None:
    monkeypatch.setattr(lab_proof, "connect", lambda: _connection(connection))


def _signals(*, rank: int | None, contribution: float | None) -> ResultSignals:
    arm = RankSignal(rank=rank, rrf_contribution=contribution)
    empty = RankSignal()
    return ResultSignals(
        fts=empty,
        trigram=arm,
        semantic=empty,
        rrf_score=contribution or 0.0,
        pre_rerank_rank=1,
        pre_rerank_score=contribution or 0.0,
        rerank_score=0.91,
        rerank_rank=1,
        final_rank=1,
    )


def _product(product_id: int, signals: ResultSignals, **overrides) -> ProductSummary:
    fields = {
        "product_id": product_id,
        "sku": f"SKU-{product_id}",
        "title": "Sonorra WHC720",
        "short_description": "Over-ear headphones.",
        "domain": "consumer_electronics",
        "category_key": "headphones",
        "category_path": "electronics/audio/headphones",
        "brand": "Sonorra",
        "model": "WHC720",
        "price_cents": 15900,
        "list_price_cents": 19900,
        "review_count": 412,
        "availability": "in_stock",
        "inventory_count": 24,
        "attributes": {},
        "tags": [],
        "signals": signals,
    }
    return ProductSummary(**(fields | overrides))


def _response(results: list[ProductSummary], *, trigram_in_pool: int) -> SearchResponse:
    return SearchResponse(
        search_event_id=uuid4(),
        query="noice cancelng hedfones",
        normalized_query="noice cancelng hedfones",
        applied_filters={},
        results=results,
        diagnostics=RetrievalDiagnostics(
            strategy="hybrid_rrf",
            embedding_model_id="cohere.embed-v4:0",
            embedding_dimensions=1024,
            rerank_model_id="cohere.rerank-v3-5:0",
            rerank_status="applied",
            retrieval_profile=RetrievalProfile(),
            candidate_counts={"trigram_in_pool": trigram_in_pool},
            stage_timings_ms={},
            total_latency_ms=120,
        ),
    )


def _lab_1_search(monkeypatch, *, solved: bool = True) -> None:
    rrf_k = RetrievalProfile().rrf_k
    results = (
        [_product(2, _signals(rank=1, contribution=1.0 / (rrf_k + 1)))]
        if solved
        else []
    )
    monkeypatch.setattr(
        lab_proof,
        "search_with_telemetry",
        lambda request: _response(results, trigram_in_pool=7 if solved else 0),
    )


def _lab_2_search(monkeypatch) -> None:
    rrf_k = RetrievalProfile().rrf_k
    contribution = 1.0 / (rrf_k + 1)
    arm = RankSignal(rank=1, rrf_contribution=contribution)
    signals = ResultSignals(
        fts=arm,
        trigram=arm,
        semantic=arm,
        rrf_score=contribution * 3,
        pre_rerank_rank=1,
        pre_rerank_score=contribution * 3,
        rerank_score=0.93,
        rerank_rank=1,
        final_rank=1,
    )
    product = _product(
        370002,
        signals,
        domain="home_office",
        category_key="office_chairs",
        attributes={"seat_depth_adjustable": True},
    )
    monkeypatch.setattr(
        lab_proof,
        "search_with_telemetry",
        lambda request: _response([product], trigram_in_pool=9),
    )


def _persisted_turn() -> dict:
    return {
        "agent_turn_id": AGENT_RUN_ID,
        "agent_session_id": SESSION_ID,
        "user_message": "Compare a keyboard and a chair",
        "assistant_message": "Both clear the budget.",
        "extracted_intent": {
            "selected_products": [
                {"product_id": 370001},
                {"product_id": 429001},
            ]
        },
        "created_at": datetime.now(UTC),
        "metadata": {},
    }


def _persisted_tools() -> list[dict]:
    return [
        {
            "search_event_id": None,
            "tool_name": "get_product_evidence",
            "outcome": "success",
            "input_payload": {"product_id": product_id},
            "output_payload": {"result_count": 2},
            "duration_ms": 40,
            "error_detail": None,
            "occurred_at": datetime.now(UTC),
        }
        for product_id in (370001, 429001)
    ] + [
        {
            "search_event_id": None,
            "tool_name": "synthesize_cited_answer",
            "outcome": "success",
            "input_payload": {},
            "output_payload": {
                "result_count": 2,
                "citations": [
                    {"number": 1, "evidence_id": 9001, "product_id": 370001},
                    {"number": 2, "evidence_id": 9002, "product_id": 429001},
                ],
            },
            "duration_ms": 900,
            "error_detail": None,
            "occurred_at": datetime.now(UTC),
        }
    ]


def _persisted_searches() -> list[dict]:
    return [
        {
            "search_event_id": uuid4(),
            "occurred_at": datetime.now(UTC),
            "filters": {
                "domain": "home_office",
                "max_price_cents": 80000,
                "in_stock_only": True,
            },
            "retrieval_profile": {},
            "source_revision": "abc",
            "dataset_manifest_sha256": "def",
            "embedding_model_id": "cohere.embed-v4:0",
            "rerank_model_id": "cohere.rerank-v3-5:0",
            "candidate_counts": {},
            "total_latency_ms": 300,
            "diagnostics": {},
        }
    ]


def _grounded_connection() -> _FakeConnection:
    return _FakeConnection(
        turn=_persisted_turn(),
        searches=_persisted_searches(),
        tools=_persisted_tools(),
    )


def _resolve_evidence(monkeypatch, *, product_ids: dict[int, int] | None = None):
    mapping = product_ids or {9001: 370001, 9002: 429001}

    def resolve(evidence_id: int):
        return {"evidence_id": evidence_id, "product_id": mapping[evidence_id]}

    monkeypatch.setattr(lab_proof, "resolve_evidence", resolve)


# ---------------------------------------------------------------------------
# Proof 1: red at birth
# ---------------------------------------------------------------------------


def test_a_reset_lab_reports_broken_source_state(monkeypatch, lab_repo: Path) -> None:
    set_isolated_lab_state(1, repo=lab_repo)
    _use(monkeypatch, _FakeConnection())
    _lab_1_search(monkeypatch, solved=False)

    assert lab_is_solved(1, repo=lab_repo) is False
    proof = lab_proof.completion_proof(1, repo=lab_repo)

    assert proof.source_state == "broken"
    assert proof.status == "fail"


def test_a_stale_aurora_function_is_reported_as_stale(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection(lab_1_definition=BROKEN_LAB_1_DEFINITION))
    _lab_1_search(monkeypatch)

    proof = lab_proof.completion_proof(1)

    assert proof.database_state == "stale"
    assert proof.status == "fail"


def test_a_collapsed_fusion_formula_is_reported_as_stale(monkeypatch) -> None:
    """Lab 2's applied-state read must see the tie the broken formula creates."""
    _use(monkeypatch, _FakeConnection(rrf_correct=False))
    _lab_2_search(monkeypatch)

    proof = lab_proof.completion_proof(2)

    assert proof.database_state == "stale"
    assert proof.status == "fail"


# ---------------------------------------------------------------------------
# Proof 2: independence
# ---------------------------------------------------------------------------


def test_editing_an_unowned_file_leaves_source_state_alone(
    monkeypatch, lab_repo: Path
) -> None:
    _use(monkeypatch, _FakeConnection())
    _lab_1_search(monkeypatch)
    before = lab_proof.completion_proof(1, repo=lab_repo).source_state

    unowned = lab_repo / INDEPENDENT_FILE
    unowned.write_text(
        unowned.read_text(encoding="utf-8") + "\n# irrelevant edit\n",
        encoding="utf-8",
    )
    after = lab_proof.completion_proof(1, repo=lab_repo).source_state

    assert before == "solved"
    assert after == before


# ---------------------------------------------------------------------------
# Proof 3: witness literals
# ---------------------------------------------------------------------------


def test_lab_1_proof_runs_four_checks(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())
    _lab_1_search(monkeypatch)

    proof = lab_proof.completion_proof(1)

    assert len(proof.checks) == 4, [check.name for check in proof.checks]
    assert proof.status == "pass"
    assert len(proof.evidence.search_event_ids) == 1
    assert proof.database_state == "applied"


def test_lab_2_proof_runs_five_checks_over_two_searches(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())
    _lab_2_search(monkeypatch)

    proof = lab_proof.completion_proof(2)

    assert len(proof.checks) == 5, [check.name for check in proof.checks]
    assert proof.status == "pass"
    assert len(proof.evidence.search_event_ids) == 2, (
        "Lab 2 proves pre-rerank repeatability, which needs two persisted runs"
    )


def test_lab_3_proof_runs_five_checks_over_persisted_rows(monkeypatch) -> None:
    _use(monkeypatch, _grounded_connection())
    _resolve_evidence(monkeypatch)

    proof = lab_proof.completion_proof(3, agent_run_id=AGENT_RUN_ID)

    assert len(proof.checks) == 5, [check.name for check in proof.checks]
    assert proof.status == "pass"
    assert proof.database_state == "not_applicable"
    assert proof.evidence.agent_run_id == AGENT_RUN_ID
    assert proof.evidence.evidence_ids == [9001, 9002]


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_lab_3_without_a_run_id_fails_naming_stage_03(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())

    proof = lab_proof.completion_proof(3)

    assert proof.status == "fail"
    assert len(proof.checks) == 5
    assert all("Stage 03" in check.detail for check in proof.checks)
    assert proof.evidence.agent_run_id is None


def test_lab_3_with_an_unknown_run_id_fails_naming_stage_03(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())

    proof = lab_proof.completion_proof(3, agent_run_id=uuid4())

    assert proof.status == "fail"
    assert all("Stage 03" in check.detail for check in proof.checks)


def test_lab_3_spends_no_agent_turn(monkeypatch) -> None:
    """Witness: the proof reads receipts; it must not call the model."""
    _use(monkeypatch, _grounded_connection())
    _resolve_evidence(monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the completion proof must not run the agent")

    monkeypatch.setattr(lab_proof, "search_with_telemetry", forbidden)

    proof = lab_proof.completion_proof(3, agent_run_id=AGENT_RUN_ID)

    assert len(proof.evidence.search_event_ids) == 1, (
        "the persisted turn's own receipts, not a receipt this proof created"
    )


def test_an_unknown_lab_is_refused(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())

    with pytest.raises(lab_proof.UnknownLab, match="fix:"):
        lab_proof.completion_proof(4)


def test_lab_state_reports_every_lab(monkeypatch) -> None:
    _use(monkeypatch, _FakeConnection())

    state = lab_proof.lab_states()

    assert [record.lab_id for record in state.labs] == [1, 2, 3]
    assert state.labs[2].database_state == "not_applicable"
    assert all(record.detail for record in state.labs)


def test_the_proof_carries_live_identity_and_the_release_baseline(
    monkeypatch,
) -> None:
    _use(monkeypatch, _FakeConnection())
    _lab_1_search(monkeypatch)

    proof = lab_proof.completion_proof(1)

    assert len(proof.identity.retrieval_fingerprint) == 64
    assert len(proof.identity.retrieval_settings_sha256) == 64
    assert proof.identity.embedding_model_id
    assert proof.identity.dataset_manifest_sha256
    assert proof.release_baseline.measured_at < proof.finished_at
    assert proof.duration_ms >= 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_routes_serve_state_and_proof(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from service.main import app

    _use(monkeypatch, _FakeConnection())
    _lab_1_search(monkeypatch)

    with TestClient(app) as client:
        state = client.get("/api/labs/state")
        proof = client.post("/api/labs/1/proof", json={"agent_run_id": None})

    assert state.status_code == 200
    assert [lab["lab_id"] for lab in state.json()["labs"]] == [1, 2, 3]
    assert proof.status_code == 200
    assert proof.json()["lab_id"] == 1
    assert len(proof.json()["checks"]) == 4


def test_an_unrouted_lab_id_is_a_404(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from service.main import app

    _use(monkeypatch, _FakeConnection())

    with TestClient(app) as client:
        response = client.post("/api/labs/9/proof", json={})

    assert response.status_code == 404
