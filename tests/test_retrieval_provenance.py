from pathlib import Path
from uuid import uuid4

from service.models import RetrievalProfile
from service.retrieval import RetrievalService


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, event):
        self.event = event
        self.executed = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, parameters=None):
        self.executed.append((sql, parameters))
        if "SELECT normalized_query" in sql:
            return _Result(self.event)
        if sql.startswith("EXPLAIN"):
            return _Result(
                {
                    "QUERY PLAN": [
                        {
                            "Plan": {
                                "Node Type": "Function Scan",
                                "Function Name": "search_hybrid_rrf",
                            }
                        }
                    ]
                }
            )
        return _Result()

    def commit(self):
        self.committed = True


class _Embedder:
    model_id = "us.cohere.embed-v4:0"

    def embed_query(self, _query):
        return [0.0] * 1024


def test_plan_capture_replays_the_persisted_production_path():
    search_event_id = uuid4()
    connection = _Connection(
        {
            "normalized_query": "quiet office keyboard",
            "filters": {"domain": "home_office"},
            "retrieval_profile": RetrievalProfile().model_dump(),
            "retrieval_strategy": "rrf_fusion+rerank+exact_sku_preservation",
        }
    )
    service = RetrievalService(
        embedding_provider=_Embedder(),
        connection_factory=lambda: connection,
    )

    response = service.capture_plan(search_event_id)

    assert response.search_event_id == search_event_id
    assert response.plan[0]["Plan"]["Function Name"] == "search_hybrid_rrf"
    statements = [sql for sql, _ in connection.executed]
    assert any("mosaic_search.configure_hnsw" in sql for sql in statements)
    explain = next(sql for sql in statements if sql.startswith("EXPLAIN"))
    assert "ANALYZE, BUFFERS, SETTINGS, FORMAT JSON" in explain
    assert "mosaic_search.search_hybrid_rrf(" in explain
    assert any("SET plan_json" in sql for sql in statements)
    assert connection.committed is True


def test_search_receipt_schema_names_every_reproducibility_input():
    telemetry = (
        Path(__file__).resolve().parents[1] / "db" / "sql" / "12_telemetry.sql"
    ).read_text(encoding="utf-8")

    for column in (
        "source_revision",
        "source_worktree_dirty",
        "dataset_manifest_sha256",
        "embedding_model_id",
        "rerank_model_id",
        "retrieval_strategy",
        "database_instance_id",
        "database_version",
        "vector_extension_version",
        "aurora_instance_class",
        "hnsw_settings",
        "plan_json",
    ):
        assert column in telemetry
