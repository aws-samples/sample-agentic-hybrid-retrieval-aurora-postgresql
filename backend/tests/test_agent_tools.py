"""Contract tests for the model-facing tool surface.

These assert the properties that distinguish agent_tools from a direct wrapper:
the model cannot supply a persona, a bad argument returns a readable failure
instead of ending the loop, returns stay small enough to fit a context window,
and the tool schemas actually describe their parameters. Nothing here calls
Aurora or Bedrock.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.app import agent_tools
from backend.app.models import DEFAULT_ROLE


class ToolSchemaTests(unittest.TestCase):
    def test_no_tool_lets_the_model_choose_a_role(self) -> None:
        for spec in agent_tools.tool_specifications():
            with self.subTest(tool=spec["name"]):
                properties = spec["inputSchema"]["json"]["properties"]
                self.assertNotIn("role", properties)

    def test_every_parameter_has_a_real_description(self) -> None:
        for spec in agent_tools.tool_specifications():
            for name, schema in spec["inputSchema"]["json"]["properties"].items():
                with self.subTest(tool=spec["name"], parameter=name):
                    description = schema.get("description", "")
                    self.assertTrue(description)
                    # Strands emits this when a docstring has no Args: entry.
                    self.assertNotEqual(description, f"Parameter {name}")

    def test_advertised_tool_list_matches_the_registered_functions(self) -> None:
        self.assertEqual(
            agent_tools.MODEL_TOOLS,
            [spec["name"] for spec in agent_tools.tool_specifications()],
        )


class RegistryPartitionTests(unittest.TestCase):
    """agent.py keeps its tool-name lists as literals to avoid importing the
    registry (which imports agent.py). This guards them against drifting from
    the registry's Strands partition, which the transports actually generate from.
    """

    def test_agent_lists_match_the_registry_strands_partition(self) -> None:
        from agent.registry import TOOLS, tools_for
        from backend.app.agent import AGENT_SELECTABLE_TOOLS, SERVER_TOOLS

        strands = [spec.name for spec in tools_for("strands")]
        selectable = [name for name in strands if TOOLS[name].strands_selectable]
        server = [name for name in strands if not TOOLS[name].strands_selectable]

        self.assertEqual(AGENT_SELECTABLE_TOOLS, selectable)
        self.assertEqual(SERVER_TOOLS, server)


class ToolFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = agent_tools.start_run(None)

    def test_bad_run_id_returns_a_recovery_instead_of_raising(self) -> None:
        for value in ("CHG-1842", "", "not-a-uuid"):
            with self.subTest(run_id=value):
                result = agent_tools.explain_ranking(value)
                self.assertFalse(result["ok"])
                self.assertIn("search_evidence", result["recovery"])

    def test_empty_query_is_rejected_before_reaching_aurora(self) -> None:
        result = agent_tools.search_evidence("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(self.run["trace"], [])

    def test_unknown_evidence_kind_names_the_valid_values(self) -> None:
        result = agent_tools.search_evidence("CHG-1842", kinds=["ticket"])
        self.assertFalse(result["ok"])
        self.assertIn("support_case", result["recovery"])

    def test_comparison_of_one_key_is_rejected(self) -> None:
        result = agent_tools.compare_sources(["CHG-1842"])
        self.assertFalse(result["ok"])

    def test_traversal_without_seeds_is_rejected(self) -> None:
        self.assertFalse(agent_tools.follow_evidence_links([])["ok"])
        self.assertFalse(agent_tools.follow_evidence_links(["  "])["ok"])


class RoleBindingTests(unittest.TestCase):
    def test_the_bound_role_reaches_the_implementation(self) -> None:
        agent_tools.start_run("admin")
        with patch(
            "backend.app.agent_tools.compare_sources_impl",
            return_value={"evidence": [], "relationships": [], "observations": []},
        ) as impl:
            agent_tools.compare_sources(["CHG-1842", "CHG-1838"])
        self.assertEqual(impl.call_args.kwargs["role"], "admin")

    def test_an_unbound_run_falls_back_to_the_default_role(self) -> None:
        agent_tools.start_run(None)
        with patch(
            "backend.app.agent_tools.compare_sources_impl",
            return_value={"evidence": [], "relationships": [], "observations": []},
        ) as impl:
            agent_tools.compare_sources(["CHG-1842", "CHG-1838"])
        self.assertEqual(impl.call_args.kwargs["role"], DEFAULT_ROLE)


class ContextCostTests(unittest.TestCase):
    def _row(self, index: int) -> dict[str, object]:
        row = {
            "external_key": f"CHG-{1000 + index}",
            "title": "Add composite index on orders",
            "evidence_kind": "change",
            "source_system": "change_management",
            "source_revision": "rev-4",
            "cluster_id": "checkout-prod-cluster-01",
            "occurred_at": "2026-03-02T14:03:00Z",
            "snippet": "Ordinary CREATE INDEX blocked writes on the orders table.",
            "match_tier": 1 if index == 0 else 2,
        }
        # Fields a model cannot act on, which the tool payload must drop.
        row.update(
            {
                "evidence_id": "1e5a4f2c-0000-4000-8000-000000000001",
                "document_id": "1e5a4f2c-0000-4000-8000-000000000002",
                "chunk_id": "1e5a4f2c-0000-4000-8000-000000000003",
                "text_position": index + 1,
                "vector_position": index + 2,
                "trigram_position": None,
                "rrf_score": 0.0491803278688525,
                "final_score": 0.0491803278688525,
                "explanation": {"weights": {"text": 2.0}},
                "search_document_hash": "0" * 64,
            }
        )
        return row

    def test_tool_payload_stays_small_and_labels_the_tier(self) -> None:
        rows = [self._row(index) for index in range(8)]
        agent_tools.start_run(None)
        with patch(
            "backend.app.agent_tools.search_evidence_impl",
            return_value={
                "run_id": "1e5a4f2c-0000-4000-8000-00000000000f",
                "candidate_count": 24,
                "match_tiers": [{"tier": 1, "count": 1}, {"tier": 2, "count": 7}],
                "results": rows,
            },
        ):
            result = agent_tools.search_evidence("CHG-1842")

        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["match"], "exact_identifier")
        self.assertEqual(result["results"][1]["match"], "fused")
        self.assertEqual([row["rank"] for row in result["results"]], list(range(1, 9)))
        for row in result["results"]:
            self.assertNotIn("evidence_id", row)
            self.assertNotIn("rrf_score", row)
            self.assertNotIn("explanation", row)
        raw = len(json.dumps({"results": rows}, default=str))
        projected = len(json.dumps(result, default=str))
        self.assertLess(projected, raw // 2)

    def test_empty_results_tell_the_model_what_to_try_next(self) -> None:
        agent_tools.start_run(None)
        with patch(
            "backend.app.agent_tools.search_evidence_impl",
            return_value={
                "run_id": "1e5a4f2c-0000-4000-8000-00000000000f",
                "candidate_count": 0,
                "match_tiers": [],
                "results": [],
            },
        ):
            result = agent_tools.search_evidence("CHG-9999")
        self.assertIn("without filters", result["note"])

    def test_string_null_scope_filters_are_normalized(self) -> None:
        agent_tools.start_run(None)
        with patch(
            "backend.app.agent_tools.search_evidence_impl",
            return_value={
                "run_id": "1e5a4f2c-0000-4000-8000-00000000000f",
                "candidate_count": 0,
                "match_tiers": [],
                "results": [],
            },
        ) as impl:
            agent_tools.search_evidence(
                "production runbook",
                cluster_id="null",
                incident_id=" none ",
                kinds=["runbook"],
            )

        self.assertIsNone(impl.call_args.kwargs["cluster_id"])
        self.assertIsNone(impl.call_args.kwargs["incident_id"])


class AnswerOfRecordTests(unittest.TestCase):
    def test_synthesis_publishes_the_validated_answer_to_the_run(self) -> None:
        run = agent_tools.start_run(None)
        self.assertIsNone(run["answer_of_record"])
        with patch(
            "backend.app.agent_tools.synthesize_cited_answer_from_runs_impl",
            return_value={
                "run_id": "1e5a4f2c-0000-4000-8000-00000000000f",
                "source_run_ids": [
                    "1e5a4f2c-0000-4000-8000-00000000000f"
                ],
                "required_kinds": ["change"],
                "answer": "CHG-1842 took a ShareLock [1].",
                "citations": [{"n": 1, "external_key": "CHG-1842"}],
                "synthesis": {"mode": "bedrock"},
            },
        ):
            result = agent_tools.synthesize_cited_answer(
                "Why did writes block?",
                ["1e5a4f2c-0000-4000-8000-00000000000f"],
            )

        self.assertEqual(run["answer_of_record"]["answer"], result["answer"])
        # The model is told not to restate it, because the caller returns it.
        self.assertIn("Do not repeat", result["instruction"])

    def test_a_failed_synthesis_leaves_no_answer_of_record(self) -> None:
        run = agent_tools.start_run(None)
        with patch(
            "backend.app.agent_tools.synthesize_cited_answer_from_runs_impl",
            side_effect=ValueError("run 1e5a not found"),
        ):
            result = agent_tools.synthesize_cited_answer(
                "Why did writes block?",
                ["1e5a4f2c-0000-4000-8000-00000000000f"],
            )
        self.assertFalse(result["ok"])
        self.assertIsNone(run["answer_of_record"])


if __name__ == "__main__":
    unittest.main()
