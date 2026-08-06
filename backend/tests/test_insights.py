from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.app.insights import (
    _collect_scans,
    _planner_summary,
    _runtime_sql,
    observability_ref,
    supervision_receipt,
)


class _ObservabilityCursor:
    def __init__(self, ref: dict[str, object]) -> None:
        self._ref = ref

    def __enter__(self) -> _ObservabilityCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, *_: object, **__: object) -> None:
        return None

    def fetchone(self) -> dict[str, object]:
        return self._ref


class _ObservabilityConnection:
    def __init__(self, ref: dict[str, object]) -> None:
        self._cursor = _ObservabilityCursor(ref)

    def __enter__(self) -> _ObservabilityConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> _ObservabilityCursor:
        return self._cursor


class _SupervisionCursor:
    def __init__(self, result_sets: list[list[dict[str, object]]]) -> None:
        self._result_sets = result_sets
        self.statements: list[str] = []

    def __enter__(self) -> _SupervisionCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, *_: object, **__: object) -> None:
        self.statements.append(statement)

    def fetchall(self) -> list[dict[str, object]]:
        return self._result_sets.pop(0)


class _SupervisionConnection:
    def __init__(self, cursor: _SupervisionCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _SupervisionConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> _SupervisionCursor:
        return self._cursor


class QueryPlanInsightTests(unittest.TestCase):
    def test_collect_scans_preserves_runtime_details_from_nested_nodes(
        self,
    ) -> None:
        plan = {
            "Node Type": "Sort",
            "Plans": [
                {
                    "Node Type": "Index Scan",
                    "Schema": "retrieval",
                    "Relation Name": "chunks",
                    "Index Name": "chunks_embedding_hnsw_idx",
                    "Actual Rows": 8,
                    "Actual Loops": 2,
                    "Actual Startup Time": 0.12,
                    "Actual Total Time": 1.75,
                    "Shared Hit Blocks": 14,
                    "Shared Read Blocks": 3,
                    "Rows Removed by Filter": 4,
                    "Filter": "(cluster_id = 'checkout-prod-cluster-01')",
                    "Index Cond": "(embedding <=> :embedding)",
                    "Recheck Cond": None,
                }
            ],
        }

        scans: list[dict[str, object]] = []
        _collect_scans(plan, scans)

        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0]["index"], "chunks_embedding_hnsw_idx")
        self.assertEqual(scans[0]["schema"], "retrieval")
        self.assertEqual(scans[0]["actual_total_time_ms"], 1.75)
        self.assertEqual(scans[0]["shared_hit_blocks"], 14)
        self.assertEqual(scans[0]["rows_removed_by_filter"], 4)
        self.assertIn("cluster_id", str(scans[0]["filter"]))

    def test_runtime_sql_is_arm_specific_and_parameterized(self) -> None:
        statement = """
            SELECT *
            FROM retrieval.semantic_search(
              p_query_embedding => %(embedding)s::vector,
              p_limit => %(result_limit)s::integer
            )
        """

        semantic = _runtime_sql("semantic", statement)
        lexical = _runtime_sql("lexical", statement)
        fuzzy = _runtime_sql("fuzzy", statement)

        self.assertIn("retrieval.configure_ann_runtime", semantic)
        self.assertIn(":embedding::vector", semantic)
        self.assertIn("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)", semantic)
        self.assertNotIn("configure_ann_runtime", lexical)
        self.assertNotIn("pg_trgm.similarity_threshold", lexical)
        self.assertIn("pg_trgm.similarity_threshold", fuzzy)
        self.assertNotIn("configure_ann_runtime", fuzzy)

    def test_planner_summary_reports_observed_hnsw_selection(self) -> None:
        summary, uses_hnsw = _planner_summary(
            "semantic",
            [{"index": "chunks_embedding_hnsw_idx"}],
            [],
        )

        self.assertTrue(uses_hnsw)
        self.assertIn("chunks_embedding_hnsw_idx", summary)
        self.assertIn("selected", summary)

    def test_planner_summary_explains_semantic_hnsw_bypass(self) -> None:
        summary, uses_hnsw = _planner_summary(
            "semantic",
            [{"index": "chunks_cluster_id_idx"}],
            [],
        )

        self.assertFalse(uses_hnsw)
        self.assertIn("No HNSW index was selected", summary)
        self.assertIn("chunks_cluster_id_idx", summary)

    def test_planner_summary_explains_fuzzy_abstention(self) -> None:
        summary, uses_hnsw = _planner_summary("fuzzy", [], [])

        self.assertIsNone(uses_hnsw)
        self.assertIn("abstained before index traversal", summary)
        self.assertIn("zero to fusion", summary)

    def test_observability_ref_emits_only_the_lock_analysis_link(self) -> None:
        ref = {
            "db_resource_id": "db-ABC123",
            "window_start": SimpleNamespace(isoformat=lambda: "2026-08-05T12:00:00Z"),
            "window_end": SimpleNamespace(isoformat=lambda: "2026-08-05T12:01:00Z"),
            "wait_event": None,
            "sql_digest": None,
            "captured_at": "2026-08-05T12:01:01Z",
        }
        settings = SimpleNamespace(
            workbench_region="us-east-1",
            workbench_lock_url_template=(
                "https://console.example.invalid/locks?"
                "region={region}&resource={db_resource_id}&start={window_start}"
            ),
        )
        with (
            patch(
                "backend.app.insights.get_dict_conn",
                return_value=_ObservabilityConnection(ref),
            ),
            patch("backend.app.insights.get_settings", return_value=settings),
            patch(
                "backend.app.insights._run_role",
                return_value="app_engineer",
            ),
        ):
            payload = observability_ref("run-123")

        self.assertEqual(
            payload["links"],
            [
                {
                    "kind": "lock_analysis",
                    "label": "Open lock analysis",
                    "url": (
                        "https://console.example.invalid/locks?"
                        "region=us-east-1&resource=db-ABC123&"
                        "start=2026-08-05T12:00:00Z"
                    ),
                }
            ],
        )

    def test_supervision_receipt_uses_the_computed_verdict_and_proposal_links(
        self,
    ) -> None:
        proposal = {
            "proposal_id": "22222222-2222-2222-2222-222222222222",
            "action_type": "create_index",
        }
        execution = {"execution_id": "33333333-3333-3333-3333-333333333333"}
        verdict = {
            "proposal_id": proposal["proposal_id"],
            "pre_execution_eligible": True,
            "pre_execution_reasons": [],
            "post_execution_validated": False,
            "post_execution_reasons": ["no execution has been recorded yet"],
        }
        citation = {
            "citation_number": 1,
            "claim": "the index is supported by live evidence",
            "is_valid": True,
            "issue": None,
        }
        cursor = _SupervisionCursor([[proposal], [execution], [verdict], [citation]])
        with (
            patch(
                "backend.app.insights.get_dict_conn",
                return_value=_SupervisionConnection(cursor),
            ),
            patch(
                "backend.app.insights._run_role",
                return_value="app_engineer",
            ),
            patch(
                "backend.app.insights.supervision_verify_sql",
                return_value={"proposal": {"statement": "SELECT 1"}},
            ) as verify_sql,
        ):
            payload = supervision_receipt("run-123")

        self.assertEqual(payload["proposal"], proposal)
        self.assertEqual(payload["execution"], execution)
        self.assertEqual(payload["verdict"], verdict)
        self.assertEqual(payload["citations"], [citation])
        self.assertEqual(payload["_verify_sql"], {"proposal": {"statement": "SELECT 1"}})
        verify_sql.assert_called_once_with(
            "run-123",
            "app_engineer",
            proposal["proposal_id"],
        )
        self.assertEqual(len(cursor.statements), 4)
        self.assertIn("proof.autonomy_readiness", cursor.statements[2])
        self.assertIn("proof.action_proposal_citations", cursor.statements[3])

    def test_supervision_receipt_preserves_a_run_without_a_proposal(self) -> None:
        cursor = _SupervisionCursor([[], [], []])
        with (
            patch(
                "backend.app.insights.get_dict_conn",
                return_value=_SupervisionConnection(cursor),
            ),
            patch(
                "backend.app.insights._run_role",
                return_value="app_engineer",
            ),
            patch(
                "backend.app.insights.supervision_verify_sql",
                return_value={"proposal": {"statement": "SELECT 1"}},
            ) as verify_sql,
        ):
            payload = supervision_receipt("run-123")

        self.assertIsNone(payload["proposal"])
        self.assertEqual(payload["citations"], [])
        self.assertIsNone(payload["execution"])
        self.assertIsNone(payload["verdict"])
        self.assertEqual(len(cursor.statements), 3)
        verify_sql.assert_called_once_with("run-123", "app_engineer", None)


if __name__ == "__main__":
    unittest.main()
