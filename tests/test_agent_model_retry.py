"""A transient Bedrock failure inside the response stream retries the model call.

Measured on a test event on 20 October: two of three Lab 3 requests failed with HTTP 503
because ConverseStream reported serviceUnavailableException mid-stream, and Strands
retries only throttling. The participant's Agent keeps Strands' default retry strategy,
so the model the application supplies has to report these failures as throttling.
"""

from unittest.mock import Mock

import pytest
from botocore.exceptions import EventStreamError
from strands import Agent

from service import agent as agent_module

REPLY = [
    {"messageStart": {"role": "assistant"}},
    {"contentBlockDelta": {"delta": {"text": "Ready."}}},
    {"contentBlockStop": {}},
    {"messageStop": {"stopReason": "end_turn"}},
]


def failing_then_replying(code: str) -> Mock:
    def interrupted():
        yield {"messageStart": {"role": "assistant"}}
        raise EventStreamError(
            {
                "Error": {
                    "Code": code,
                    "Message": "Bedrock is unable to process your request.",
                }
            },
            "ConverseStream",
        )

    client = Mock()
    client.converse_stream.side_effect = [
        {"stream": interrupted()},
        {"stream": iter(REPLY)},
    ]
    return client


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def immediately(_delay):
        return None

    monkeypatch.setattr("strands.event_loop._retry.asyncio.sleep", immediately)


def participant_agent(client: Mock) -> Agent:
    model = agent_module.RetryingBedrockModel(model_id="model", region_name="us-east-1")
    model.client = client
    return Agent(model=model, callback_handler=None)


@pytest.mark.parametrize(
    "code",
    [
        "serviceUnavailableException",
        "modelStreamErrorException",
        "internalServerException",
    ],
)
def test_a_transient_stream_failure_is_retried_and_the_turn_answers(code):
    client = failing_then_replying(code)

    result = participant_agent(client)("Help me complete my setup.")

    assert str(result).strip() == "Ready."
    assert client.converse_stream.call_count == 2


def test_a_request_error_is_not_retried():
    client = failing_then_replying("validationException")

    with pytest.raises(EventStreamError):
        participant_agent(client)("Help me complete my setup.")
    assert client.converse_stream.call_count == 1
