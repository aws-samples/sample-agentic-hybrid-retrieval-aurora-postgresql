"""Contract tests for the Strands agent path.

These run the real Strands event loop over the real tool decorators with a
scripted model, so they cover the wiring that a live Bedrock call would hide:
that the tool-call budget is enforced, that the answer returned to the caller is
the citation-validated one rather than the model's prose, and that a run which
never synthesizes says so instead of passing narration off as an answer.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import patch

from strands.models import Model

from backend.app.models import AgentAnswerRequest
from backend.app.strands_agent import (
    answer_question_with_strands,
    stream_answer_with_strands,
)

RUN_ID = "1e5a4f2c-0000-4000-8000-00000000000f"
VALIDATED_ANSWER = (
    "CHG-A1B2C3D4-01 ran the unbatched priority_tier backfill that blocked writers [1]."
)

SEARCH_RESULT = {
    "run_id": RUN_ID,
    "candidate_count": 24,
    "match_tiers": [{"tier": 1, "count": 1}],
    "results": [
        {
            "external_key": "CHG-A1B2C3D4-01",
            "title": "Unbatched priority_tier backfill",
            "evidence_kind": "change",
            "source_revision": "rev-4",
            "snippet": "The open priority_tier backfill blocked hot writers.",
            "match_tier": 1,
        }
    ],
}
SYNTHESIS_RESULT = {
    "run_id": RUN_ID,
    "source_run_ids": [RUN_ID],
    "required_kinds": ["change"],
    "answer": VALIDATED_ANSWER,
    "citations": [
        {
            "n": 1,
            "external_key": "CHG-A1B2C3D4-01",
            "source_revision": "rev-4",
        }
    ],
    "synthesis": {"mode": "bedrock"},
}


class ScriptedModel(Model):
    """A model that emits a fixed sequence of turns, so the loop is testable.

    Each script entry is either a tool name to call or a string to say. The last
    entry ends the turn.
    """

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.turns = 0

    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        step = self.script[min(self.turns, len(self.script) - 1)]
        self.turns += 1
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, tuple):
            name, arguments = step
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": f"t{self.turns}", "name": name}}
                }
            }
            yield {
                "contentBlockDelta": {"delta": {"toolUse": {"input": arguments}}}
            }
            yield {"contentBlockStop": {}}
            stop_reason = "tool_use"
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step}}}
            yield {"contentBlockStop": {}}
            stop_reason = "end_turn"
        yield {"messageStop": {"stopReason": stop_reason}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
                "metrics": {"latencyMs": 1},
            }
        }


def _agent_with(script: list[Any]):
    def build(*, max_tool_calls: int = 12):
        from strands import Agent

        from backend.app import agent_tools
        from backend.app.strands_agent import SYSTEM_PROMPT, _ToolCallBudget

        return Agent(
            model=ScriptedModel(script),
            tools=list(agent_tools.TOOL_FUNCTIONS),
            system_prompt=SYSTEM_PROMPT,
            hooks=[_ToolCallBudget(max_tool_calls)],
            callback_handler=None,
        )

    return build


class StrandsAgentTests(unittest.TestCase):
    def test_stream_publishes_validated_citations_before_answer_tokens(self) -> None:
        script = [
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}'),
            (
                "synthesize_cited_answer",
                '{"question": "Why did writes block?", "run_ids": ["%s"]}' % RUN_ID,
            ),
            "The cited answer is ready.",
        ]

        async def collect_events() -> list[dict[str, Any]]:
            return [
                event
                async for event in stream_answer_with_strands(
                    AgentAnswerRequest(question="Why did writes block?")
                )
            ]

        with (
            patch(
                "backend.app.agent_tools.search_evidence_impl",
                return_value=SEARCH_RESULT,
            ),
            patch(
                "backend.app.agent_tools.synthesize_cited_answer_from_runs_impl",
                return_value=SYNTHESIS_RESULT,
            ),
            patch("backend.app.strands_agent.build_agent", _agent_with(script)),
        ):
            events = asyncio.run(collect_events())

        event_types = [event["type"] for event in events]
        self.assertLess(
            event_types.index("citations"),
            event_types.index("answer_token"),
        )

    def test_caller_receives_the_validated_answer_not_the_models_prose(self) -> None:
        script = [
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}'),
            (
                "synthesize_cited_answer",
                '{"question": "Why did writes block?", "run_ids": ["%s"]}' % RUN_ID,
            ),
            "Here is my own rewrite of the answer with different citations [9].",
        ]
        with (
            patch(
                "backend.app.agent_tools.search_evidence_impl",
                return_value=SEARCH_RESULT,
            ),
            patch(
                "backend.app.agent_tools.synthesize_cited_answer_from_runs_impl",
                return_value=SYNTHESIS_RESULT,
            ),
            patch("backend.app.strands_agent.build_agent", _agent_with(script)),
        ):
            result = answer_question_with_strands(
                AgentAnswerRequest(question="Why did writes block?")
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"], VALIDATED_ANSWER)
        self.assertEqual([c["n"] for c in result["citations"]], [1])
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertIn("rewrite", result["agent_commentary"])
        self.assertEqual(
            [call["tool"] for call in result["tool_calls"]],
            ["search_evidence", "synthesize_cited_answer"],
        )

    def test_a_run_that_never_synthesizes_reports_no_answer(self) -> None:
        script = ["I could not find anything relevant."]
        with patch("backend.app.strands_agent.build_agent", _agent_with(script)):
            result = answer_question_with_strands(
                AgentAnswerRequest(question="Why did writes block?")
            )

        self.assertEqual(result["status"], "unsynthesized")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["citations"], [])
        self.assertIn("not citation-validated", result["note"])

    def test_the_tool_call_budget_stops_a_looping_model(self) -> None:
        # Strands continues a tool cycle by recursing in Python, so a model that
        # ignores the cancellation must be stopped or it exhausts the stack.
        script = [
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}')
        ]
        with (
            patch(
                "backend.app.agent_tools.search_evidence_impl",
                return_value=SEARCH_RESULT,
            ),
            patch("backend.app.strands_agent.build_agent", _agent_with(script)),
        ):
            result = answer_question_with_strands(
                AgentAnswerRequest(question="Why did writes block?", max_tool_calls=3)
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("budget of 3", result["error"])
        self.assertEqual(len(result["tool_calls"]), 3)
        self.assertNotIn("recursion", result["error"].lower())

    def test_a_failed_loop_still_returns_an_answer_aurora_validated(self) -> None:
        script = [
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}'),
            (
                "synthesize_cited_answer",
                '{"question": "Why did writes block?", "run_ids": ["%s"]}' % RUN_ID,
            ),
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}'),
        ]
        with (
            patch(
                "backend.app.agent_tools.search_evidence_impl",
                return_value=SEARCH_RESULT,
            ),
            patch(
                "backend.app.agent_tools.synthesize_cited_answer_from_runs_impl",
                return_value=SYNTHESIS_RESULT,
            ),
            patch("backend.app.strands_agent.build_agent", _agent_with(script)),
        ):
            result = answer_question_with_strands(
                AgentAnswerRequest(question="Why did writes block?", max_tool_calls=2)
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"], VALIDATED_ANSWER)
        self.assertIn("budget of 2", result["error"])

    def test_the_request_role_reaches_the_tools(self) -> None:
        script = [
            ("search_evidence", '{"query": "CHG-A1B2C3D4-01"}'),
            "Done.",
        ]
        with (
            patch(
                "backend.app.agent_tools.search_evidence_impl",
                return_value=SEARCH_RESULT,
            ) as impl,
            patch("backend.app.strands_agent.build_agent", _agent_with(script)),
        ):
            answer_question_with_strands(
                AgentAnswerRequest(question="Why?", role="dba")
            )

        self.assertEqual(impl.call_args.kwargs["role"], "dba")


if __name__ == "__main__":
    unittest.main()
