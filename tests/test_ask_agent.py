"""`scripts/ask_agent.py` prints the deployed agent's answer of record from the terminal."""

from uuid import UUID

import pytest

from scripts import ask_agent
from scripts.validate_lab import LabValidationError
from service.models import AgentResponse

RUN = UUID("27086027-0000-4000-8000-000000000001")


def product(product_id, title):
    return {
        "product_id": product_id, "sku": "B0C2WWCFQB", "title": title,
        "short_description": "", "domain": "consumer_electronics",
        "category_key": "headphones", "category_path": "Electronics > Headphones",
        "brand": "Logitech", "model": "Zone 900", "price_cents": None,
        "list_price_cents": None, "review_count": 10, "availability": None,
        "inventory_count": None, "attributes": {}, "tags": [],
    }


def grounded():
    return AgentResponse(
        agent_run_id=RUN,
        question="Help me complete my setup",
        answer="The Logitech Zone 900 has active noise cancellation [1]. "
               "One reviewer found it comfortable [2].",
        plan=[],
        recommendations=[product(1492978, "Logitech Zone 900")],
        citations=[
            {"number": 1, "evidence_id": 11, "evidence_type": "product_spec",
             "product_id": 1492978, "source_uri": "amazon-reviews-2023:meta/B0C2WWCFQB",
             "revision": "v2", "title": "Listing", "quote": "Active noise cancellation"},
            {"number": 2, "evidence_id": 12, "evidence_type": "customer_review",
             "product_id": 1492978, "source_uri": "amazon-reviews-2023:review/R1",
             "revision": "v2", "title": "Review", "quote": "They are comfortable. " * 20},
        ],
        trace=[
            {"sequence": 1, "tool": "search_products", "detail": "", "latency_ms": 812.4},
            {"sequence": 2, "tool": "synthesize_cited_answer", "detail": ""},
        ],
        outcome="grounded",
    ).model_dump(mode="json")


def declined():
    return AgentResponse(
        agent_run_id=RUN,
        question="Does the ViewSonic charge at 100W?",
        answer="The retrieved sources do not establish USB-C 100W charging.",
        plan=[], recommendations=[], citations=[],
        trace=[{"sequence": 1, "tool": "synthesize_cited_answer", "detail": "",
                "outcome": "denied"}],
        outcome="declined",
        decline_reason="unsupported_requirements",
    ).model_dump(mode="json")


def test_a_grounded_answer_shows_trace_products_and_each_citation():
    text = ask_agent.render(grounded())

    assert "The Logitech Zone 900 has active noise cancellation [1]." in text
    assert "1  search_products" in text and "812 ms" in text
    assert "1492978  Logitech Zone 900" in text
    assert "[1] product_spec     1492978  B0C2WWCFQB @ v2" in text
    assert '      "Active noise cancellation"' in text
    assert "[2] customer_review  1492978" in text
    assert "OUTCOME: grounded" in text
    assert f"Run ID: {RUN}" in text
    assert "DECLINE REASON" not in text


def test_a_long_quote_is_shortened_but_the_answer_is_not():
    text = ask_agent.render(grounded())

    lines = text.splitlines()
    quote_line = lines[next(i for i, line in enumerate(lines) if "customer_review" in line) + 1]
    assert quote_line.rstrip().endswith("…\"")
    assert len(quote_line) < 200


def test_a_declined_answer_names_its_reason_and_says_nothing_was_cited():
    text = ask_agent.render(declined())

    assert "OUTCOME: declined" in text
    assert "DECLINE REASON: unsupported_requirements" in text
    assert "synthesize_cited_answer  denied" in text
    assert "CITATIONS\n  none" in text


def test_main_posts_the_question_to_the_ask_mosaic_route(monkeypatch, capsys):
    calls = []

    def fake_request(base_url, path, payload=None):
        calls.append((base_url, path, payload))
        return declined()

    monkeypatch.setattr(ask_agent, "_request", fake_request)
    code = ask_agent.main(["Does the ViewSonic charge at 100W?"])

    assert code == 0
    assert calls == [("http://127.0.0.1:8000", "/api/agent/answer",
                      {"question": "Does the ViewSonic charge at 100W?"})]
    assert "OUTCOME: declined" in capsys.readouterr().out


def test_an_api_failure_is_reported_and_exits_non_zero(monkeypatch, capsys):
    def failing(base_url, path, payload=None):
        raise LabValidationError("/api/agent/answer returned HTTP 503: runtime unavailable")

    monkeypatch.setattr(ask_agent, "_request", failing)
    code = ask_agent.main(["Find headphones for calls"])

    assert code == 1
    assert "HTTP 503" in capsys.readouterr().err


def test_the_command_string_is_the_one_participants_type():
    from service.participant_commands import ask_agent as command

    assert command("…") == 'uv run python scripts/ask_agent.py "…"'


@pytest.mark.parametrize("question", ["", "abc"])
def test_a_question_too_short_for_the_api_is_refused_locally(question, capsys):
    assert ask_agent.main([question]) == 2
    assert "at least 4 characters" in capsys.readouterr().err
