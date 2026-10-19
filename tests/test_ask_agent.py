"""`scripts/ask_agent.py` prints the deployed agent's answer of record from the terminal."""

from uuid import UUID

import pytest

from scripts import ask_agent
from scripts.validate_lab import LabValidationError
from service.models import AgentResponse

RUN = UUID("27086027-0000-4000-8000-000000000001")


def product(product_id, title):
    return {
        "product_id": product_id,
        "sku": "B0C2WWCFQB",
        "title": title,
        "short_description": "",
        "domain": "consumer_electronics",
        "category_key": "headphones",
        "category_path": "Electronics > Headphones",
        "brand": "Logitech",
        "model": "Zone 900",
        "price_cents": None,
        "list_price_cents": None,
        "review_count": 10,
        "availability": None,
        "inventory_count": None,
        "attributes": {},
        "tags": [],
    }


def grounded():
    return AgentResponse(
        agent_run_id=RUN,
        question="Help me complete my setup",
        answer="The Logitech Zone 900 has active noise cancellation [1]. "
        "One reviewer found it comfortable [2].",
        plan=[
            {
                "query": "Steelcase Gesture office chair",
                "filters": {"domain": "home_office", "category_key": "office_chair"},
                "purpose": "Find the chair Alex named",
            }
        ],
        recommendations=[product(1492978, "Logitech Zone 900")],
        citations=[
            {
                "number": 1,
                "evidence_id": 11,
                "evidence_type": "product_spec",
                "product_id": 1492978,
                "source_uri": "amazon-reviews-2023:meta/B0C2WWCFQB",
                "revision": "v2",
                "title": "Listing",
                "quote": "Active noise cancellation",
            },
            {
                "number": 2,
                "evidence_id": 12,
                "evidence_type": "customer_review",
                "product_id": 1492978,
                "source_uri": "amazon-reviews-2023:review/R1",
                "revision": "v2",
                "title": "Review",
                "quote": "They are comfortable. " * 20,
            },
        ],
        trace=[
            {
                "sequence": 1,
                "tool": "search_products",
                "detail": "",
                "latency_ms": 812.4,
            },
            {"sequence": 2, "tool": "synthesize_cited_answer", "detail": ""},
        ],
        outcome="grounded",
    ).model_dump(mode="json")


def declined():
    return AgentResponse(
        agent_run_id=RUN,
        question="Does the ViewSonic charge at 100W?",
        answer="The retrieved sources do not establish USB-C 100W charging.",
        plan=[],
        recommendations=[],
        citations=[],
        trace=[
            {
                "sequence": 1,
                "tool": "synthesize_cited_answer",
                "detail": "",
                "outcome": "denied",
            }
        ],
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
    assert "  1  Steelcase Gesture office chair" in text
    assert "domain=home_office, category_key=office_chair" in text
    assert "Find the chair Alex named" in text
    assert "DECLINE REASON" not in text


def test_a_long_quote_is_shortened_but_the_answer_is_not():
    text = ask_agent.render(grounded())

    lines = text.splitlines()
    quote_line = lines[
        next(i for i, line in enumerate(lines) if "customer_review" in line) + 1
    ]
    assert quote_line.rstrip().endswith('…"')
    assert len(quote_line) < 200


def test_every_line_fits_a_laptop_terminal_without_wrapping(monkeypatch):
    """Code Editor's terminal on a 16-inch laptop holds 124 characters a line; a wrapped
    title or quote breaks mid-word in the guide's screenshots and on screen."""
    monkeypatch.setattr(ask_agent, "participant_sql_digest", lambda: "a" * 64)
    run = gateway_run("a" * 64)
    run["recommendations"] = [product(1551237, "ViewSonic VG2756-4K 27 Inch IPS 4K " * 6)]
    run["citations"] = grounded()["citations"]

    text = ask_agent.render(run)

    assert max(len(line) for line in text.splitlines()) <= ask_agent.LINE_CHARS
    assert "1551237  ViewSonic VG2756-4K 27 Inch IPS 4K" in text


def test_a_quote_shows_the_source_line_breaks_as_spaces():
    run = grounded()
    run["citations"][1]["quote"] = "Great dock.<br /><br />Charges my laptop.<BR>Loud fan."

    text = ask_agent.render(run)

    assert '"Great dock. Charges my laptop. Loud fan."' in text
    assert "<br" not in text.lower()


def test_a_declined_answer_names_its_reason_and_says_nothing_was_cited():
    text = ask_agent.render(declined())

    assert "OUTCOME: declined" in text
    assert "DECLINE REASON: unsupported_requirements" in text
    assert "synthesize_cited_answer  denied" in text
    assert "CITATIONS\n  none" in text
    assert "PLAN\n  none" in text


def test_main_posts_the_question_to_the_ask_mosaic_route(monkeypatch, capsys):
    calls = []

    def fake_request(base_url, path, payload=None, *, timeout):
        calls.append((base_url, path, payload))
        assert timeout == ask_agent.response_timeout()
        return declined()

    monkeypatch.setattr(ask_agent, "_request", fake_request)
    code = ask_agent.main(["Does the ViewSonic charge at 100W?"])

    assert code == 0
    assert calls == [
        (
            "http://127.0.0.1:8000",
            "/api/agent/answer",
            {"question": "Does the ViewSonic charge at 100W?"},
        )
    ]
    assert "OUTCOME: declined" in capsys.readouterr().out


def test_an_api_failure_is_reported_and_exits_non_zero(monkeypatch, capsys):
    def failing(base_url, path, payload=None, **_options):
        raise LabValidationError(
            "/api/agent/answer returned HTTP 503: runtime unavailable"
        )

    monkeypatch.setattr(ask_agent, "_request", failing)
    code = ask_agent.main(["Find headphones for calls"])

    assert code == 1
    assert "HTTP 503" in capsys.readouterr().err


def test_the_terminal_waits_longer_than_the_api_can_take():
    """The API waits for Runtime up to the deadline, plus 30 s read and 10 s connect.

    A client that gave up first lost the Run ID of a run the API went on to save.
    """
    from service.config import get_settings

    api_worst_case = get_settings().agent_turn_deadline_seconds + 30 + 10

    assert ask_agent.response_timeout() > api_worst_case


def test_a_slow_answer_is_reported_with_its_wait_and_a_fix(monkeypatch, capsys):
    def slow(_request, timeout):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("scripts.validate_lab.urlopen", slow)
    code = ask_agent.main(["Find headphones for calls"])

    error = capsys.readouterr().err
    assert code == 1
    assert f"no response within {ask_agent.response_timeout():.0f} s" in error
    assert "run the command again" in error


def test_the_command_string_is_the_one_participants_type():
    from service.participant_commands import ask_agent as command

    assert command("…") == 'uv run python scripts/ask_agent.py "…"'


@pytest.mark.parametrize("question", ["", "abc"])
def test_a_question_too_short_for_the_api_is_refused_locally(question, capsys):
    assert ask_agent.main([question]) == 2
    assert "at least 4 characters" in capsys.readouterr().err


def gateway_run(search_sql_sha256):
    """A deployed run: catalog tools through Gateway, a final step by the application."""
    return AgentResponse(
        agent_run_id=RUN,
        question="Which 27 inch 4K monitor charges a laptop at 100W?",
        answer="The retrieved sources do not establish USB-C 100W laptop charging.",
        plan=[],
        recommendations=[],
        citations=[],
        trace=[
            {
                "sequence": 1,
                "tool": "search_products",
                "detail": "",
                "route": "gateway",
                "search_sql_sha256": search_sql_sha256,
            },
            {
                "sequence": 2,
                "tool": "get_product_evidence",
                "detail": "",
                "route": "gateway",
            },
            {
                "sequence": 3,
                "tool": "synthesize_cited_answer",
                "detail": "",
                "outcome": "denied",
                "origin": "controller_fallback",
            },
        ],
        outcome="declined",
        decline_reason="unsupported_requirements",
    ).model_dump(mode="json")


def test_a_search_through_gateway_says_it_ran_the_lab_sql(monkeypatch):
    monkeypatch.setattr(ask_agent, "participant_sql_digest", lambda: "a" * 64)

    text = ask_agent.render(gateway_run("a" * 64))

    assert "1  search_products          success   through AgentCore Gateway" in text
    assert (
        "Aurora ran your Lab 1 and Lab 2 SQL (aaaaaaaaaaaa), the same as your lab files"
        in text
    )
    assert "2  get_product_evidence     success   through AgentCore Gateway" in text


def test_a_search_that_ran_other_sql_says_so_and_how_to_apply(monkeypatch):
    monkeypatch.setattr(ask_agent, "participant_sql_digest", lambda: "a" * 64)

    text = ask_agent.render(gateway_run("b" * 64))

    assert (
        "Aurora ran search SQL bbbbbbbbbbbb, not your lab files' aaaaaaaaaaaa" in text
    )
    assert "uv run python scripts/apply_search_functions.py" in text
    assert "the same as your lab files" not in text


def test_a_search_with_no_sql_record_says_so(monkeypatch):
    monkeypatch.setattr(ask_agent, "participant_sql_digest", lambda: "a" * 64)

    text = ask_agent.render(gateway_run(None))

    assert "Aurora has no record of which search SQL ran" in text


def test_a_step_the_application_ran_is_labelled(monkeypatch):
    monkeypatch.setattr(ask_agent, "participant_sql_digest", lambda: "a" * 64)

    text = ask_agent.render(gateway_run("a" * 64))

    assert "3  synthesize_cited_answer  denied   run by the application" in text


def test_an_agent_that_reports_no_route_prints_no_sql_line():
    """An agent deployed before routes were recorded keeps its old trace."""
    text = ask_agent.render(grounded())

    assert "Gateway" not in text and "Aurora ran" not in text


def test_the_setup_command_asks_the_question_completion_checks():
    """The shell hands ask_agent.py the request completion compares, word for word."""
    import shlex

    from service import lab_checks
    from service.participant_commands import ask_setup

    words = shlex.split(ask_setup())
    mission = lab_checks.mission_for_lab(3)
    asked = lab_checks.mission_request_check(mission, {"question": words[-1]})

    assert words[:4] == ["uv", "run", "python", "scripts/ask_agent.py"]
    assert asked.passed, asked.detail
