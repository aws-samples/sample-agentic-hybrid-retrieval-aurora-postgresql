"""A draft an answer check refuses is a refusal on every surface, not a failed step.

The terminal reads `refused` yellow and a model or service failure red. The Ask Mosaic
panel and Playground read the trace the API serves, so the trace itself says which it was.
The stored `outcome` stays `error`: `mosaic.tool_outcome` has no refused value.
"""

import pytest
from test_grounding_refusal_causes import _state

from service import agent, agent_tools
from service.answerability import PartlySupportedSelection
from service.synthesis import ANSWER_CHECK_ERRORS, SynthesisOutputError

REFUSAL = (
    "claim support: passage 3: The passage has no citation of its own. It compares the "
    "listed 90W to the shopper's 100W need, a conclusion that rests on uncited "
    "reasoning.; remove the unsupported claim"
)


def _draft_that_raises(monkeypatch, error: Exception) -> dict:
    def synthesize(*_a, **_k):
        raise error

    monkeypatch.setattr(agent_tools, "set_declined_answer_of_record", lambda _s: False)
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesize)
    state = _state(101)
    with agent_tools.bind_run(state):
        agent_tools.synthesize_cited_answer("Which charger?", [101])
    return agent._trace_steps(state)[-1].model_dump()


def test_a_draft_the_claim_review_refuses_is_traced_as_refused(monkeypatch):
    step = _draft_that_raises(monkeypatch, SynthesisOutputError(REFUSAL))

    assert step["tool"] == "synthesize_cited_answer"
    assert step["outcome"] == "error"
    assert step["refused"] is True


# A partly supported selection is its own `denied` step, never an `error` one.
DRAFT_CHECKS = [c for c in ANSWER_CHECK_ERRORS if c is not PartlySupportedSelection]


@pytest.mark.parametrize("error_type", DRAFT_CHECKS)
def test_every_answer_check_failure_is_traced_as_refused(monkeypatch, error_type):
    step = _draft_that_raises(monkeypatch, error_type("a rule the draft broke"))

    assert step["outcome"] == "error"
    assert step["refused"] is True


@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError("slow")])
def test_a_model_or_service_failure_stays_an_error_that_is_not_refused(
    monkeypatch, error
):
    step = _draft_that_raises(monkeypatch, error)

    assert step["outcome"] == "error"
    assert step["refused"] is False


def test_the_terminal_classifies_with_the_same_checks_as_the_trace():
    from scripts import ask_agent

    assert ask_agent.ANSWER_CHECKS == tuple(c.__name__ for c in ANSWER_CHECK_ERRORS)
