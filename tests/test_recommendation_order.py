"""Cards must follow the answer even when synthesis changes its leading pick."""

from unittest.mock import Mock

import pytest
from test_agent_coverage_decline import run_state
from test_synthesis_claims import evidence, product

from service import agent_tools
from service.models import AgentCitation
from service.synthesis import recommendations_in_answer_order


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
