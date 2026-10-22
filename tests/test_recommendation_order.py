"""Cards must follow the answer even when synthesis changes its leading pick."""

from unittest.mock import Mock

import pytest
from test_agent_coverage_decline import run_state
from test_synthesis_claims import evidence, product

from service import agent_tools
from service.models import AgentCitation
from service.synthesis import lead_with_better_rated, recommendations_in_answer_order


@pytest.fixture
def picks():
    return [
        product(product_id=1, title="NovaLogic OH-M349 Core", model="OH-M349"),
        product(product_id=2, title="NovaVision OH-N697 Core", model="OH-N697"),
        product(product_id=3, title="VectorGrid OH-C014S Essential", model="OH-C014S"),
    ]


@pytest.fixture
def citations(picks):
    return [
        AgentCitation(
            number=index,
            evidence_id=index,
            evidence_type="specification",
            product_id=pick.product_id,
            source_uri=f"mosaic://evidence/{index}",
            revision="r1",
            title=pick.title,
            quote="Microphone details.",
        )
        for index, pick in enumerate(picks, 1)
    ]


def test_answer_order_is_neither_selection_order_nor_source_number(picks, citations):
    answer = (
        "NovaVision OH-N697 Core is the best fit [2].\n\n"
        "Other options: NovaLogic OH-M349 Core [1], then "
        "VectorGrid OH-C014S Essential [3]."
    )
    ordered = recommendations_in_answer_order(answer, picks, citations)
    assert [pick.product_id for pick in ordered] == [2, 1, 3]
    assert [pick.product_id for pick in picks] == [1, 2, 3]
    assert [citation.number for citation in citations] == [1, 2, 3]


def test_named_products_take_precedence_over_other_products_supporting_citations(
    picks, citations
):
    # A comparison can cite both products. The named subject still comes first.
    ordered = recommendations_in_answer_order(
        "OH-N697 leads the comparison [1] [2]. OH-M349 is another option [1].",
        picks,
        citations,
    )
    assert [pick.product_id for pick in ordered] == [2, 1, 3]


def test_citation_only_mentions_are_stable_and_do_not_duplicate_cards(picks, citations):
    ordered = recommendations_in_answer_order(
        "Start with this option [3]. More detail [3].", picks, citations
    )
    assert [pick.product_id for pick in ordered] == [3, 1, 2]
    assert recommendations_in_answer_order("No named preference.", picks, []) == picks


@pytest.mark.parametrize("fallback", [False, True])
def test_both_finalizers_store_answer_order_without_rewriting_evidence(
    monkeypatch, picks, citations, fallback
):
    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2, 3]}}
    ]
    state["evidence"] = {
        pick.product_id: evidence("Microphone details.").model_copy(
            update={"product_id": pick.product_id, "evidence_id": pick.product_id}
        )
        for pick in picks
    }
    state["evidence_by_product"] = {
        pick.product_id: [pick.product_id] for pick in picks
    }
    answer = "OH-N697 is the best fit [2]. Other options: OH-M349 [1], OH-C014S [3]."
    synthesis = Mock(return_value=(answer, citations, {}))
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(state)
    try:
        if fallback:
            agent_tools.finalize_retrieved_answer(
                state["question"], product_ids=[1, 2, 3]
            )
        else:
            result = agent_tools.synthesize_cited_answer(state["question"], [1, 2, 3])
            assert result["ok"] is True
    finally:
        agent_tools._RUN.reset(token)
    synthesis.assert_called_once()
    assert [p.product_id for p in synthesis.call_args.args[1]] == [1, 2, 3]
    record = state["answer_of_record"]
    assert [p.product_id for p in record["recommendations"]] == [2, 1, 3]
    assert record["answer"] == answer
    assert record["citations"] == citations


def test_failed_draft_cannot_drop_a_product_intent_on_retry(monkeypatch, picks):
    from service.synthesis import SynthesisOutputError

    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2]}}
    ]
    state["evidence"] = {
        i: evidence("Supported specification.").model_copy(
            update={"product_id": i, "evidence_id": i}
        )
        for i in (1, 2)
    }
    state["evidence_by_product"] = {1: [1], 2: [2]}
    synthesis = Mock(
        side_effect=SynthesisOutputError("A product claim lacks its citation")
    )
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(state)
    try:
        failed = agent_tools.synthesize_cited_answer(state["question"], [1, 2])
        assert failed["ok"] is False
        assert "same product IDs [1, 2]" in failed["recovery"]
        dropped = agent_tools.synthesize_cited_answer(state["question"], [1])
        assert dropped["ok"] is False
        assert "same product IDs [1, 2]" in dropped["recovery"]
        synthesis.assert_called_once()
        assert state["answer_of_record"] is None
        synthesis.side_effect = None
        synthesis.return_value = ("Supported choice [1][2].", [], {})
        retry = agent_tools.synthesize_cited_answer(state["question"], [1, 2])
        assert retry["ok"] is True
        assert [p.product_id for p in synthesis.call_args.args[1]] == [1, 2]
    finally:
        agent_tools._RUN.reset(token)


@pytest.mark.parametrize(
    "error,named",
    [
        ("answerability", True),
        ("output", True),
        ("other", False),
    ],
)
def test_trace_names_the_check_that_failed_synthesis(monkeypatch, picks, error, named):
    from service.answerability import AnswerabilityError
    from service.synthesis import SynthesisOutputError

    message = (
        "answerability: inconsistent support verdict; agree with every product decision"
    )
    raised = {
        "answerability": AnswerabilityError(message),
        "output": SynthesisOutputError(message),
        "other": RuntimeError(message),
    }[error]
    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["evidence"] = {
        i: evidence("Supported specification.").model_copy(
            update={"product_id": i, "evidence_id": i}
        )
        for i in (1, 2)
    }
    state["evidence_by_product"] = {1: [1], 2: [2]}
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2]}}
    ]
    monkeypatch.setattr(agent_tools, "synthesize_answer", Mock(side_effect=raised))
    token = agent_tools._RUN.set(state)
    try:
        assert (
            agent_tools.synthesize_cited_answer(state["question"], [1, 2])["ok"]
            is False
        )
    finally:
        agent_tools._RUN.reset(token)
    detail = state["trace"][-1]["detail"]
    assert (message in detail) is named
    assert detail.startswith(f"Synthesis failed with {type(raised).__name__}")


def test_a_partly_supported_selection_is_narrowed_never_recommended(monkeypatch, picks):
    from service.answerability import PartlySupportedSelection

    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["evidence"] = {
        i: evidence("Supported specification.").model_copy(
            update={"product_id": i, "evidence_id": i}
        )
        for i in (1, 2, 3)
    }
    state["evidence_by_product"] = {1: [1], 2: [2], 3: [3]}
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2, 3]}}
    ]
    synthesis = Mock(
        side_effect=[
            PartlySupportedSelection([1, 3], [2]),
            ("OH-M349 [1] and OH-C014S [3] are well reviewed.", [], {}),
        ]
    )
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(state)
    try:
        refused = agent_tools.synthesize_cited_answer(state["question"], [1, 2, 3])
        assert refused["ok"] is False
        assert "only product IDs [1, 3]" in refused["recovery"]
        assert state["answer_of_record"] is None
        assert state["trace"][-1]["outcome"] == "denied"
        narrowed = agent_tools.synthesize_cited_answer(state["question"], [1, 3])
        assert narrowed["ok"] is True
    finally:
        agent_tools._RUN.reset(token)
    assert [p.product_id for p in synthesis.call_args.args[1]] == [1, 3]
    assert 2 not in [p.product_id for p in state["answer_of_record"]["recommendations"]]


@pytest.mark.parametrize("second_partial", [False, True])
def test_the_fallback_narrows_once_and_never_recommends_a_refused_product(
    monkeypatch, picks, second_partial
):
    from service.answerability import PartlySupportedSelection

    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["evidence"] = {
        i: evidence("Supported specification.").model_copy(
            update={"product_id": i, "evidence_id": i}
        )
        for i in (1, 2, 3)
    }
    state["evidence_by_product"] = {1: [1], 2: [2], 3: [3]}
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2, 3]}}
    ]
    synthesis = Mock(
        side_effect=[
            PartlySupportedSelection([1, 3], [2]),
            PartlySupportedSelection([1], [3])
            if second_partial
            else ("OH-M349 [1] and OH-C014S [3] are well reviewed.", [], {}),
        ]
    )
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(state)
    try:
        if second_partial:
            with pytest.raises(PartlySupportedSelection):
                agent_tools.finalize_retrieved_answer(
                    state["question"], product_ids=[1, 2, 3]
                )
        else:
            agent_tools.finalize_retrieved_answer(
                state["question"], product_ids=[1, 2, 3]
            )
    finally:
        agent_tools._RUN.reset(token)
    assert synthesis.call_count == 2
    assert [p.product_id for p in synthesis.call_args.args[1]] == [1, 3]
    refused = [step for step in state["trace"] if step.get("outcome") == "denied"]
    assert refused[0]["origin"] == "controller_fallback"
    if second_partial:
        assert state["answer_of_record"] is None
    else:
        recommended = [
            p.product_id for p in state["answer_of_record"]["recommendations"]
        ]
        assert 2 not in recommended
        assert state["trace"][-1]["arguments"]["product_ids"] == [1, 3]


def _rated(product_id, rating, kind="headphones", name=None):
    name = name or f"Brand{product_id} Model{product_id}"
    return product(
        product_id=product_id,
        title=name,
        brand=name.split()[0],
        model=name.split()[1],
        category_key=kind,
        rating=rating,
    )


def test_a_much_lower_rated_first_pick_yields_the_lead_to_one_of_its_kind():
    picks = [_rated(1, 1.8), _rated(2, 3.8), _rated(3, 4.0)]

    ordered, promoted = lead_with_better_rated("headphones to help me focus", picks)

    # The earliest pick a star or more above the lead takes it; the rest keep the
    # agent's order, so the 3.8 leads even though the 4.0 is rated higher.
    assert [pick.product_id for pick in ordered] == [2, 1, 3]
    assert promoted.product_id == 2
    assert [pick.product_id for pick in picks] == [1, 2, 3]


@pytest.mark.parametrize(
    ("lead", "other", "moves"),
    [
        (4.3, 5.0, False),
        (3.2, 4.1, False),
        (3.1, 4.1, True),
        (1.8, 2.8, True),
        (1.8, 4.0, True),
    ],
)
def test_the_lead_moves_only_at_a_whole_star_or_more(lead, other, moves):
    ordered, promoted = lead_with_better_rated("q", [_rated(1, lead), _rated(2, other)])

    assert (promoted is not None) is moves
    assert ordered[0].product_id == (2 if moves else 1)


def test_picks_of_other_kinds_unrated_picks_and_named_products_keep_the_agents_order():
    chair = _rated(2, 4.8, kind="chair")
    assert lead_with_better_rated("q", [_rated(1, 1.8), chair])[1] is None
    assert lead_with_better_rated("q", [_rated(1, None), _rated(2, 4.8)])[1] is None
    unrated_then_rated = [_rated(1, 1.8), _rated(2, None), _rated(3, 4.0)]
    assert lead_with_better_rated("q", unrated_then_rated)[1].product_id == 3

    named = [_rated(1, 1.8, name="Vibe VS-888"), _rated(2, 4.0)]
    ordered, promoted = lead_with_better_rated("I'm looking at the Vibe VS-888.", named)
    assert promoted is None
    assert [pick.product_id for pick in ordered] == [1, 2]


@pytest.mark.parametrize("fallback", [False, True])
def test_both_finalizers_hand_synthesis_the_better_rated_lead_and_say_why(
    monkeypatch, fallback
):
    picks = [_rated(1, 1.8, name="Vibe VS-888"), _rated(2, 4.0, name="Sierra NC-2")]
    state = run_state(coverage=[], products={pick.product_id: pick for pick in picks})
    state["question"] = "headphones that help me focus when working from home"
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2]}}
    ]
    state["evidence"] = {
        pick.product_id: evidence("Noise cancellation.").model_copy(
            update={"product_id": pick.product_id, "evidence_id": pick.product_id}
        )
        for pick in picks
    }
    state["evidence_by_product"] = {1: [1], 2: [2]}
    synthesis = Mock(return_value=("Sierra NC-2 fits [2]. Vibe VS-888 [1].", [], {}))
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(state)
    try:
        if fallback:
            agent_tools.finalize_retrieved_answer(state["question"], product_ids=[1, 2])
        else:
            assert agent_tools.synthesize_cited_answer(state["question"], [1, 2])["ok"]
    finally:
        agent_tools._RUN.reset(token)

    assert [p.product_id for p in synthesis.call_args.args[1]] == [2, 1]
    # Evidence is numbered in the same order: a model shown the first pick's records
    # as [1] calls that pick the best fit, whatever order the products came in.
    assert [record.product_id for record in synthesis.call_args.args[2]] == [2, 1]
    step = state["trace"][-1]
    assert step["tool"] == "synthesize_cited_answer"
    assert step["arguments"]["product_ids"] == ([2, 1] if fallback else [1, 2])
    assert (
        "Sierra NC-2 (4.0 stars) leads instead of Vibe VS-888 (1.8 stars), the agent's "
        "first pick, rated at least 1 star lower than a pick of the same kind."
    ) in step["detail"]


class _Writer:
    """An answerability review that supports every pick, then the scripted drafts."""

    def __init__(self, picks, drafts):
        self.picks, self.drafts, self.calls = picks, list(drafts), []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            review = {
                "request_supported": True,
                "reason": "supported",
                "products": [
                    {
                        "product_id": p.product_id,
                        "supported": True,
                        "evidence_ids": [p.product_id],
                    }
                    for p in self.picks
                ],
            }
            content = {"toolUse": {"name": "record_answerability", "input": review}}
            stop = "tool_use"
        else:
            content, stop = {"text": self.drafts.pop(0)}, "end_turn"
        return {
            "stopReason": stop,
            "output": {"message": {"content": [content]}},
            "usage": {"inputTokens": 1, "outputTokens": 1},
        }


def _write(picks, drafts, question="headphones that help me focus"):
    from types import SimpleNamespace

    from service.synthesis import synthesize_cited_answer

    records = [
        evidence("Active noise cancellation.").model_copy(
            update={"product_id": p.product_id, "evidence_id": p.product_id}
        )
        for p in picks
    ]
    writer = _Writer(picks, drafts)
    answer, _, _ = synthesize_cited_answer(
        question,
        picks,
        records,
        client=writer,
        settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
    )
    return answer, writer


VIBE_FIRST = "Vibe VS-888 has active noise cancellation [2]. Sierra NC-2 does too [1]."
SIERRA_FIRST = (
    "Sierra NC-2 has active noise cancellation [1]. Vibe VS-888 does too [2]."
)


def test_a_draft_leading_with_a_much_lower_rated_pick_is_rewritten_to_lead_with_the_other():
    picks = [_rated(2, 4.0, name="Sierra NC-2"), _rated(1, 1.8, name="Vibe VS-888")]

    answer, writer = _write(picks, [VIBE_FIRST, SIERRA_FIRST])

    assert answer.startswith("Sierra NC-2")
    repair = writer.calls[-1]["messages"][-1]["content"][0]["text"]
    assert "Name Sierra NC-2 first, as the best fit" in repair
    assert "1.8" not in repair and "4.0" not in repair


def test_an_answer_that_keeps_the_lower_rated_lead_after_repair_is_refused():
    from service.synthesis import SynthesisOutputError

    picks = [_rated(2, 4.0, name="Sierra NC-2"), _rated(1, 1.8, name="Vibe VS-888")]

    with pytest.raises(SynthesisOutputError, match="leads with Vibe VS-888"):
        _write(picks, [VIBE_FIRST, VIBE_FIRST])


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("I'm looking at the Vibe VS-888. Is it good for focus?", "headphones"),
        ("focus", "chair"),
    ],
)
def test_a_named_or_different_kind_lead_is_written_as_the_model_chose(question, kind):
    picks = [
        _rated(2, 4.0, name="Sierra NC-2", kind=kind),
        _rated(1, 1.8, name="Vibe VS-888"),
    ]

    answer, writer = _write(picks, [VIBE_FIRST], question=question)

    assert answer.startswith("Vibe VS-888")
    assert len(writer.calls) == 2
