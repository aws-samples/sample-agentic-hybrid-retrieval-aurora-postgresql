"""The streaming loop's failure log names the error type, never the shopper's words."""

import asyncio
import logging

from service.agent import ProductDiscoveryAgent
from service.models import AgentRequest

QUESTION = "headphones for my private medical office, budget 123"


def test_a_failed_stream_loop_logs_the_error_type_only(monkeypatch, caplog):
    class Failing:
        def stream_async(self, prompt):
            raise ValueError(f"model rejected: {prompt}")

    monkeypatch.setattr("service.agent.build_agent", lambda **_: Failing())
    monkeypatch.setattr(
        "service.agent._agent_prompt", lambda request, _state: request.question
    )

    async def run():
        return [
            event
            async for event in ProductDiscoveryAgent()._stream_agent_loop(
                AgentRequest(question=QUESTION), {}, 5.0
            )
        ]

    with caplog.at_level(logging.WARNING, logger="service.agent"):
        events = asyncio.run(run())
    assert "loop_outcome" in events[-1]
    logged = "\n".join(
        f"{record.getMessage()}\n{record.exc_text or ''}" for record in caplog.records
    )
    assert "error_type=ValueError" in logged
    assert "medical" not in logged
    assert all(record.exc_info is None for record in caplog.records)
