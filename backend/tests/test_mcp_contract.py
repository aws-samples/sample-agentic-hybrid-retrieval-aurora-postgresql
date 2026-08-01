from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from lambda_mcp.handler import lambda_handler


def _payload(response: dict) -> dict:
    return json.loads(response["content"][0]["text"])


class LambdaMcpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        receipt_patch = patch("backend.app.contracts.record_transport_invocation")
        self.record_transport_invocation = receipt_patch.start()
        self.addCleanup(receipt_patch.stop)

    def test_direct_event_arguments_are_not_discarded(self) -> None:
        response = lambda_handler(
            {
                "tool": "decompose_question",
                "question": "Why did CHG-1842 cause INC-2047?",
            },
            None,
        )

        self.assertFalse(response["isError"])
        result = _payload(response)["result"]
        self.assertEqual(result["contract_version"], "1.0.0")
        self.assertEqual(result["identified_keys"], ["CHG-1842", "INC-2047"])

    def test_search_uses_database_incident_filter_names(self) -> None:
        with patch(
            "lambda_mcp.generated_dispatch.search_evidence_impl",
            return_value={"run_id": "receipt"},
        ) as search:
            response = lambda_handler(
                {
                    "name": "search_evidence",
                    "arguments": {
                        "query": "blocked writes",
                        "kinds": ["incident", "change"],
                        "cluster_id": "checkout-prod-cluster-01",
                        "incident_id": "INC-2047",
                        "limit": 5,
                    },
                },
                None,
            )

        self.assertFalse(response["isError"])
        search.assert_called_once_with(
            query="blocked writes",
            kinds=["incident", "change"],
            cluster_id="checkout-prod-cluster-01",
            incident_id="INC-2047",
            account_name=None,
            severities=None,
            environment=None,
            service_name=None,
            engine_version=None,
            aws_region=None,
            start_date=None,
            end_date=None,
            role="app_engineer",
            limit=5,
            candidate_pool=24,
            rrf_k=60,
            w_text=2.0,
            w_vector=1.0,
            w_trgm=1.0,
            fuzzy_threshold=0.3,
            ef_search=40,
            iterative_scan="strict_order",
            rerank=None,
        )

    def test_zero_weights_and_flags_survive_the_gateway(self) -> None:
        with patch(
            "lambda_mcp.generated_dispatch.search_evidence_impl",
            return_value={"run_id": "receipt"},
        ) as search:
            response = lambda_handler(
                {
                    "name": "search_evidence",
                    "arguments": {
                        "query": "blocked writes",
                        "w_text": 0,
                        "w_vector": 0,
                        "w_trgm": 0,
                        "rerank": False,
                    },
                },
                None,
            )

        self.assertFalse(response["isError"])
        passed = search.call_args.kwargs
        self.assertEqual(passed["w_text"], 0.0)
        self.assertEqual(passed["w_vector"], 0.0)
        self.assertEqual(passed["w_trgm"], 0.0)
        self.assertIs(passed["rerank"], False)

    def test_zero_escalation_budget_survives_the_gateway(self) -> None:
        with patch("backend.app.agent.answer_question") as answer:
            answer.return_value = {"run_id": "receipt"}
            response = lambda_handler(
                {
                    "name": "answer_with_citations",
                    "arguments": {
                        "question": "Why did CHG-1842 cause INC-2047?",
                        "max_escalations": 0,
                    },
                },
                None,
            )

        self.assertFalse(response["isError"])
        request = answer.call_args.args[0]
        self.assertEqual(request.max_escalations, 0)

    def test_unknown_tool_returns_mcp_error(self) -> None:
        response = lambda_handler({"tool": "not_a_tool"}, None)

        self.assertTrue(response["isError"])
        self.assertIn("Unknown tool", _payload(response)["error"])


if __name__ == "__main__":
    unittest.main()
