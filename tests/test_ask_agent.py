"""`scripts/ask_agent.py` prints the deployed agent's answer of record from the terminal."""

import http.client
import io
import json
import re
import sys
from io import BytesIO
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest

from scripts import ask_agent
from scripts.progress import bar
from service.models import AgentResponse

RUN = UUID("27086027-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def no_saved_100w_answer(monkeypatch):
    """Aurora stays a boundary: no 100W answer is saved unless a test says so."""
    monkeypatch.setattr(ask_agent, "follow_up_saved_now", lambda: False)


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
    run = grounded()
    # One sentence, so the line the answer cited is itself too long for a terminal line.
    run["citations"][1]["quote"] = "They are comfortable and " * 10 + "light."
    text = ask_agent.render(run)

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
    run["recommendations"] = [
        product(1551237, "ViewSonic VG2756-4K 27 Inch IPS 4K " * 6)
    ]
    run["citations"] = grounded()["citations"]

    text = ask_agent.render(run)

    assert max(len(line) for line in text.splitlines()) <= ask_agent.LINE_CHARS
    assert "1551237  ViewSonic VG2756-4K 27 Inch IPS 4K" in text


def test_a_quote_shows_the_source_line_breaks_as_spaces():
    run = grounded()
    run["citations"][1]["quote"] = (
        "Great dock.<br /><br />Charges my laptop.<BR>Loud fan."
    )

    text = ask_agent.render(run)

    # A break ends a line, as a sentence does; the line the answer cited is quoted whole.
    assert '"Charges my laptop."' in text
    assert "<br" not in text.lower()


def test_a_declined_answer_names_its_reason_and_says_nothing_was_cited():
    text = ask_agent.render(declined())

    assert "OUTCOME: declined" in text
    assert "DECLINE REASON: unsupported_requirements" in text
    assert "synthesize_cited_answer  denied" in text
    assert "CITATIONS\n  none" in text
    assert "PLAN\n  none" in text


class FakeStream:
    """The streaming route's response at the HTTP boundary: server-sent event lines."""

    def __init__(self, *events):
        self.lines = [
            line.encode()
            for name, data in events
            for line in (f"event: {name}\n", f"data: {json.dumps(data)}\n", "\n")
        ]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *_):
        return False


def stage(identifier, title):
    return ("stage", {"id": identifier, "title": title, "path": "full_retrieval"})


def test_main_streams_the_question_through_the_ask_mosaic_route(monkeypatch, capsys):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, json.loads(request.data), timeout))
        return FakeStream(
            stage("understand", "Interpret request"),
            stage("retrieve", "Retrieve evidence"),
            ("tool", {"name": "search_products"}),
            ("partial", {"partial": {}}),
            stage("rank", "Compare ranks"),
            ("tool", {"name": "compare_products"}),
            stage("answer", "Compose cited answer"),
            ("complete", {"response": declined()}),
        )

    monkeypatch.setattr(ask_agent, "urlopen", fake_urlopen)
    code = ask_agent.main(["Does the ViewSonic charge at 100W?"])

    assert code == 0
    assert calls == [
        (
            "http://127.0.0.1:8000/api/agent/answer/stream",
            {"question": "Does the ViewSonic charge at 100W?"},
            ask_agent.response_timeout(),
        )
    ]
    out = capsys.readouterr().out
    for index, title in enumerate(
        (
            "Interpret request",
            "Retrieve evidence",
            "Compare ranks",
            "Compose cited answer",
        )
    ):
        assert f"{bar(index, 4)}  {title}, " in out
    assert f"{bar(1, 1)}  answered in " in out
    calls = [
        line.split(",")[0].strip() for line in out.splitlines() if "tool call" in line
    ]
    assert calls == ["tool call  search_products", "tool call  compare_products"]
    assert "OUTCOME: declined" in out


class FakeWaiting:
    """The waiting line's seam: what it was told to say, and that it was taken down."""

    def __init__(self, _stream):
        self.said, self.stopped = [], False
        FakeWaiting.last = self

    def show(self, head):
        self.said.append(head)

    def stop(self):
        self.stopped = True


def on_a_terminal(monkeypatch):
    monkeypatch.setattr(ask_agent, "can_redraw", lambda _stream: True)
    monkeypatch.setattr(ask_agent, "Waiting", FakeWaiting)


def answered_in_pieces(run, size=7):
    """The route's last events: the checked answer in pieces, then the saved run."""
    answer = run["answer"]
    pieces = [answer[index : index + size] for index in range(0, len(answer), size)]
    return (
        ("answer_start", {"response": {**run, "answer": ""}}),
        *(("answer_delta", {"delta": piece}) for piece in pieces),
        ("complete", {"response": run}),
    )


def test_on_a_terminal_the_stages_share_one_line_and_tool_calls_stay(
    monkeypatch, capsys
):
    on_a_terminal(monkeypatch)
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            ("tool", {"name": "search_products"}),
            stage("retrieve", "Retrieve evidence"),
            ("tool", {"name": "synthesize_cited_answer"}),
            stage("answer", "Compose cited answer"),
            *answered_in_pieces(grounded()),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 0
    out = capsys.readouterr().out

    assert "Interpret request" not in out and "Retrieve evidence" not in out
    assert [line.split(",")[0].strip() for line in out.splitlines()[:2]] == [
        "tool call  search_products",
        "tool call  synthesize_cited_answer",
    ]
    # The route names each tool before the stage it opens; the line keeps the tool.
    assert FakeWaiting.last.said == [
        f"{bar(0, 4)}  Interpret request",
        f"{bar(0, 4)}  Interpret request: search_products",
        f"{bar(1, 4)}  Retrieve evidence: search_products",
        f"{bar(1, 4)}  Retrieve evidence: {ask_agent.WAITING_ON['synthesize_cited_answer']}",
        f"{bar(3, 4)}  Compose cited answer: "
        + ask_agent.WAITING_ON["synthesize_cited_answer"],
    ]
    assert FakeWaiting.last.stopped


def test_on_a_terminal_the_answer_arrives_once_and_reads_as_the_saved_run(
    monkeypatch, capsys
):
    """Printed as it arrives or printed whole, the report is the same text."""
    on_a_terminal(monkeypatch)
    run = grounded()
    run["answer"] = (
        "First paragraph with a claim [1].\n\n- A point that cites [2].\nLast line."
    )
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"), *answered_in_pieces(run)
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 0
    out = capsys.readouterr().out

    progress, report = out.split("\n\n", 1)
    assert progress.startswith(f"{bar(1, 1)}  answered in ")
    assert report == (
        ask_agent.render(run)
        + "\n\nNext: check completion on your newest setup run:\n"
        + "uv run python scripts/grade_setup_run.py\n"
    )
    assert out.count("ANSWER") == 1


LAB_3_COMPLETE_NEXT = (
    "\n\nNext: the guide's next step. Lab 3 is complete, so this run needs no "
    "completion check.\n"
)


@pytest.mark.parametrize("asked", ["setup request", "another question"])
def test_once_lab_3_is_complete_an_answer_points_on_to_the_guide(
    asked, monkeypatch, capsys
):
    """Go deeper's questions come after completion; none of them is graded."""
    from service.lab_checks import mission_for_lab

    question = (
        mission_for_lab(3)["query"] if asked == "setup request" else "Find a desk lamp"
    )
    monkeypatch.setattr(ask_agent, "lab_3_solved", lambda: True)
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(*answered_in_pieces(grounded())),
    )
    assert ask_agent.main([question]) == 0

    assert capsys.readouterr().out.endswith(LAB_3_COMPLETE_NEXT)


def test_before_lab_3_is_complete_an_answer_points_to_the_completion_check(
    monkeypatch, capsys
):
    monkeypatch.setattr(ask_agent, "lab_3_solved", lambda: False)
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(*answered_in_pieces(grounded())),
    )
    assert ask_agent.main(["Find a desk lamp"]) == 0

    assert capsys.readouterr().out.endswith(
        "\n\nNext: check completion on your newest setup run:\n"
        "uv run python scripts/grade_setup_run.py\n"
    )


def refused_draft(sequence):
    return {
        "sequence": sequence,
        "tool": "synthesize_cited_answer",
        "outcome": "error",
        "detail": "Synthesis failed with SynthesisTruncated: the draft was cut off",
    }


def test_a_refused_draft_is_named_when_it_happens_and_only_once(monkeypatch, capsys):
    """Each partial carries the whole trace so far; a refusal already shown stays shown."""
    first, search = refused_draft(2), {"sequence": 1, "tool": "search_products"}
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            ("tool", {"name": "synthesize_cited_answer"}),
            ("partial", {"partial": {"trace": [search, first]}}),
            ("tool", {"name": "synthesize_cited_answer"}),
            ("partial", {"partial": {"trace": [search, first]}}),
            ("partial", {"partial": {"trace": [search, first, refused_draft(3)]}}),
            ("partial", {"partial": {}}),
            ("complete", {"response": declined()}),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 0
    lines = capsys.readouterr().out.split("answered in")[0].splitlines()

    said = "      draft refused: it was cut off before it finished"
    assert [line for line in lines if "draft refused" in line] == [said, said]
    assert (
        lines[lines.index(said) + 1] == "      The agent is told why and drafts again."
    )
    assert lines.index(said) < len(lines) - 1 - lines[::-1].index(
        next(line for line in lines[::-1] if "tool call" in line)
    )


def test_on_a_terminal_a_stopped_run_takes_the_waiting_line_down(monkeypatch, capsys):
    on_a_terminal(monkeypatch)
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            ("error", {"detail": "The Retrieval agent stopped."}),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 1
    assert FakeWaiting.last.stopped
    assert "The Retrieval agent stopped." in capsys.readouterr().err


def test_the_reference_agent_notice_is_printed_before_the_progress(monkeypatch, capsys):
    detail = (
        "This answer comes from the reference Retrieval agent this account was prepared "
        "with. In Lab 3 you build and deploy your own, and from then on your questions go "
        "to it."
    )
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            ("notice", {"code": "reference_agent", "detail": detail}),
            stage("understand", "Interpret request"),
            ("complete", {"response": declined()}),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 0
    lines = capsys.readouterr().out.splitlines()
    progress = next(i for i, line in enumerate(lines) if "Interpret request" in line)
    note = lines[:progress]
    assert " ".join(" ".join(note).split()) == f"NOTE {detail}"
    assert max(len(line) for line in note) <= ask_agent.LINE_CHARS


def test_the_bar_never_moves_back_when_the_agent_searches_again(monkeypatch, capsys):
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            stage("rank", "Compare ranks"),
            stage("retrieve", "Retrieve evidence"),
            stage("future", "A stage this client does not know"),
            ("complete", {"response": declined()}),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 0
    out = capsys.readouterr().out
    assert "Retrieve evidence" not in out
    assert "A stage this client does not know" not in out


def test_a_stream_error_is_reported_and_exits_non_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            ("error", {"detail": "Amazon Bedrock request failed."}),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 1
    assert "stopped: Amazon Bedrock request failed." in capsys.readouterr().err


def test_a_refused_answer_prints_the_run_id_that_records_each_draft(
    monkeypatch, capsys
):
    run_id = "6f1c2b8e-0d7a-4f43-9a51-2f7d3c9e8b10"
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"),
            (
                "error",
                {
                    "detail": "The answer checks refused every draft of this answer.",
                    "agent_run_id": run_id,
                    "code": "grounding_contract",
                },
            ),
        ),
    )
    assert ask_agent.main(["Find headphones for calls"]) == 1
    err = capsys.readouterr().err
    assert "refused every draft of this answer." in err
    assert f"Run ID: {run_id}" in err


def test_an_api_failure_is_reported_and_exits_non_zero(monkeypatch, capsys):
    def failing(request, timeout):
        raise HTTPError(
            request.full_url, 503, "Service Unavailable", {}, BytesIO(b"busy")
        )

    monkeypatch.setattr(ask_agent, "urlopen", failing)
    code = ask_agent.main(["Find headphones for calls"])

    assert code == 1
    assert "HTTP 503: busy" in capsys.readouterr().err


def test_an_api_refusal_prints_its_reason_not_the_json(monkeypatch, capsys):
    reason = (
        "Your Retrieval agent has not been deployed since Lab 3 started at 00:28 UTC. "
        "Next: deploy with uv run python scripts/deploy_agentcore.py deploy."
    )

    def refusing(request, timeout):
        body = json.dumps({"detail": reason}).encode()
        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, BytesIO(body))

    monkeypatch.setattr(ask_agent, "urlopen", refusing)
    code = ask_agent.main(["Find headphones for calls"])

    err = capsys.readouterr().err
    assert code == 1
    assert f"HTTP 503: {reason}".replace(" Next: ", "\n\nNext: ") in err
    assert "detail" not in err


def test_ctrl_c_stops_the_wait_in_one_line_without_a_traceback(monkeypatch, capsys):
    def interrupted(request, timeout):
        raise KeyboardInterrupt

    monkeypatch.setattr(ask_agent, "urlopen", interrupted)
    code = ask_agent.main(["Find headphones for calls"])

    err = capsys.readouterr().err
    assert code == 130
    assert "Stopped waiting" in err
    assert "may still finish this run" in err
    assert "Traceback" not in err and "KeyboardInterrupt" not in err
    # The participant chose to stop, so nothing failed and there is no one to tell.
    assert "then ask again" in err and "fails twice" not in err


def test_the_terminal_waits_longer_than_the_api_can_take():
    """The API waits for Runtime up to the deadline, plus 30 s read and 10 s connect.

    A client that gave up first lost the Run ID of a run the API went on to save.
    """
    from service.config import get_settings

    api_worst_case = get_settings().agent_turn_deadline_seconds + 30 + 10

    assert ask_agent.response_timeout() > api_worst_case


@pytest.mark.parametrize(
    "lost", ["interrupt", "eof", "disconnect", "timeout", "wrapped-timeout", "relay"]
)
@pytest.mark.parametrize("request_kind", ["setup", "100W", "other"])
def test_lost_answer_checks_saved_lab_work_before_a_retry(
    monkeypatch, capsys, lost, request_kind
):
    from service.lab_checks import mission_for_lab
    from service.participant_commands import ask_agent_command, grade_setup_run_command

    mission = mission_for_lab(3)
    question = {
        "setup": mission["query"].upper(),
        "100W": mission["changed_requirement"]["query"],
        "other": "Find headphones for calls",
    }[request_kind]

    def lose_response(*_args, **_kwargs):
        if lost == "eof":
            return FakeStream(stage("understand", "Interpret request"))
        if lost == "relay":
            return FakeStream(
                (
                    "error",
                    {"code": "stream_interrupted", "detail": "Stream interrupted."},
                )
            )
        raise {
            "interrupt": KeyboardInterrupt(),
            "disconnect": http.client.RemoteDisconnected(),
            "timeout": TimeoutError(),
            "wrapped-timeout": URLError(TimeoutError()),
        }[lost]

    monkeypatch.setattr(ask_agent, "urlopen", lose_response)
    assert ask_agent.main([question]) == (130 if lost == "interrupt" else 1)
    error = capsys.readouterr().err
    assert error.count("Next:") == 1
    expected = (
        grade_setup_run_command()
        if request_kind != "other"
        else ask_agent_command(question)
    )
    assert error.rstrip().splitlines()[-1] == expected
    if request_kind != "other":
        assert "ask_agent.py" not in error and "run the command again" not in error


def test_a_slow_answer_is_reported_with_its_wait_and_a_fix(monkeypatch, capsys):
    def slow(_request, timeout):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(ask_agent, "urlopen", slow)
    code = ask_agent.main(["Find headphones for calls"])

    error = capsys.readouterr().err
    assert code == 1
    assert f"no response within {ask_agent.response_timeout():.0f} s" in error
    assert "run the command again" in error


def test_the_command_string_is_the_one_participants_type():
    from service.participant_commands import ask_agent_command

    assert ask_agent_command("…") == 'uv run python scripts/ask_agent.py "…"'


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
    from service.participant_commands import ask_setup_command

    words = shlex.split(ask_setup_command())
    mission = lab_checks.mission_for_lab(3)
    asked = lab_checks.mission_request_check(mission, {"question": words[-1]})

    assert words[:4] == ["uv", "run", "python", "scripts/ask_agent.py"]
    assert asked.passed, asked.detail


@pytest.mark.parametrize(
    "failure",
    [
        http.client.IncompleteRead(b"partial", 100),
        http.client.RemoteDisconnected("Remote end closed connection"),
        json.JSONDecodeError("Expecting value", "{", 1),
    ],
    ids=["incomplete read", "remote disconnect", "broken event"],
)
def test_a_stream_that_breaks_mid_answer_is_a_clean_exit_not_a_traceback(
    monkeypatch, capsys, failure
):
    class Breaking:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def __iter__(self):
            yield b"event: stage\n"
            yield (
                b"data: "
                + json.dumps(
                    {"id": "understand", "title": "Interpret request"}
                ).encode()
                + b"\n"
            )
            yield b"\n"
            raise failure

    monkeypatch.setattr(ask_agent, "urlopen", lambda *_a, **_k: Breaking())

    code = ask_agent.main(["Find headphones for calls"])

    captured = capsys.readouterr()
    assert code == 1
    assert "broke off mid-answer" in captured.err
    assert type(failure).__name__ in captured.err
    assert "may still have saved this run" in captured.err
    assert "Traceback" not in captured.err


def test_a_deleted_lab_sql_file_does_not_stop_the_run_id_printing(monkeypatch):
    from service.participant_commands import STATUS

    def deleted():
        raise FileNotFoundError("labs/lab1_retrieve/hybrid_search.sql")

    monkeypatch.setattr(ask_agent, "participant_sql_digest", deleted)

    text = ask_agent.render(gateway_run("a" * 64))

    assert text.splitlines()[-1].startswith("Run ID: ")
    assert "could not be read" in text and STATUS in text


def test_the_answer_wraps_between_words_never_inside_a_hyphenated_one():
    run = grounded()
    run["answer"] = "x" * 80 + " noise-cancelling headphones " + "y" * 40

    lines = ask_agent.render(run).splitlines()

    answer = [line for line in lines if line.startswith("  x") or "noise" in line]
    assert len(answer) >= 2
    assert all(len(line) <= ask_agent.LINE_CHARS for line in answer)
    assert all(not line.endswith("-") for line in answer)
    assert any("noise-cancelling" in line for line in answer)


def refused_then_grounded(detail):
    run = grounded()
    run["trace"] = [
        {"sequence": 1, "tool": "search_products", "detail": "", "outcome": "success"},
        {
            "sequence": 2,
            "tool": "synthesize_cited_answer",
            "detail": detail,
            "outcome": "error",
        },
        {
            "sequence": 3,
            "tool": "synthesize_cited_answer",
            "detail": "",
            "outcome": "success",
        },
    ]
    return run


def reason_under(lines: list[str], step: int) -> str:
    """The reason printed under a trace step, rejoined from the lines it wraps onto."""
    taken = []
    for line in lines[step + 1 :]:
        if not line.startswith("     "):
            break
        taken.append(line.strip())
    return " ".join(taken)


@pytest.mark.parametrize(
    ("detail", "said"),
    [
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized sentence contains "
                "unsupported numeric claim or availability claim ['100W'] for product 1551237: "
                "- If 100W is firm, confirm the charger. Cite the record that states it."
            ),
            "draft refused: it stated 100W, which no cited record supports",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized claim naming product "
                "1551237 does not cite evidence for that product: No, the records do not show it."
            ),
            "draft refused: it named product 1551237 without citing its records",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: unsupported compatibility claim "
                "'works with your laptop' in: - The ViewSonic works with your laptop. Cite a "
                "source that states that relationship, or say the sources do not state it."
            ),
            "draft refused: it claimed 'works with your laptop', which no cited record supports",
        ),
        (
            "Synthesis failed with SynthesisTruncated: the model stopped at max_tokens.",
            "draft refused: it was cut off before it finished",
        ),
        (
            "Synthesis failed with SynthesisOutputError: a rule this script does not know.",
            "draft refused by the answer check",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized sentence contains "
                "unsupported numeric claim or availability claim ['1,000 mAh', '$129.99'] "
                "for product 5: It holds 1,000 mAh and costs $129.99 [1]."
            ),
            "draft refused: it stated 1,000 mAh, $129.99, which no cited record supports",
        ),
        (
            (
                "Synthesis failed with SynthesisStopped: Synthesized answer stopped with "
                "'content_filtered'; a filtered or interrupted answer cannot become the "
                "answer of record"
            ),
            "draft refused: it stopped before it finished (content_filtered)",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized answer did not "
                "cite every selected product: missing [1551237]."
            ),
            "draft refused: it left a selected product without a citation",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized answer contains a "
                "link 'https://example.invalid/x' that is not the source address of a "
                "cited record. Remove it; the citations already link the sources."
            ),
            "draft refused: it contained a link that is not a cited source",
        ),
        (
            "Synthesis failed with ThrottlingException.",
            "draft step failed (ThrottlingException), not refused by a check",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: claim support: passage 8 "
                "rests on record 1's scope note, \"Historical parent-product listing. "
                'Confirm exact variant and current offer separately.", which is '
                "Mosaic's note on what the record can establish, not its words; write "
                "that caveat as a plain step without a citation"
            ),
            (
                "draft refused: it cited record 1 for a caveat that is Mosaic's note, "
                "not the record's own words"
            ),
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: claim support: passage 8 "
                'cites [1][2][3][4][5][6] but states no product fact: "Sources: [1][2] '
                'headset, [3][4] monitor, [5][6] chair."; write advice, checks and '
                "headings without citations, or state the fact the record gives"
            ),
            (
                "draft refused: it put citations on a line that states no product "
                'fact: "Sources: [1][2] headset, [3][4] monitor, [5][6] chair."'
            ),
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: claim support: passage 3 is "
                "marked supported without a source quote; quote the cited record that "
                "supports it"
            ),
            "draft refused: the check could not confirm every claim against its source",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized answer did not "
                "cite catalog evidence"
            ),
            "draft refused: it cited no source",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: Synthesized answer cited "
                "evidence outside the retrieved set"
            ),
            "draft refused: it cited a source number that is not among the retrieved records",
        ),
        (
            (
                "Synthesis failed with SynthesisOutputError: The answer leads with Chair "
                "A, which is rated at least 1 star lower than Chair B, a pick of the same "
                "kind. Name Chair B first, as the best fit, and write about the other "
                "after it"
            ),
            "draft refused: it led with a pick rated at least a star below another of its kind",
        ),
    ],
)
def test_a_refused_draft_says_in_plain_words_why_it_was_refused(detail, said):
    """A rejected draft used to show only `error`, which participants read as a failure."""
    text = ask_agent.render(refused_then_grounded(detail))

    lines = text.splitlines()
    step = next(
        i for i, line in enumerate(lines) if "2  synthesize_cited_answer" in line
    )
    refused = said.startswith("draft refused")
    assert ("refused" if refused else "error") in lines[step]
    assert ("error" in lines[step]) is not refused, "a refused draft is not an error"
    assert lines[step].endswith("the agent drafted again") is refused
    assert reason_under(lines, step) == said
    assert "SynthesisOutputError" not in text and "Synthesis failed" not in text
    assert max(len(line) for line in lines) <= ask_agent.LINE_CHARS


CLAIM_REVIEW_REFUSAL = (
    "Synthesis failed with SynthesisOutputError: claim support: passage 1: Features and "
    'warranty are supported, but calling it "the chair for your setup" asserts a fit with '
    "the other products that no source establishes.; remove the unsupported claim or "
    "cite evidence that supports it"
)


def test_the_claim_reviews_own_reason_prints_whole_inside_the_terminal():
    """Measured on the 10 November event, where this refusal printed no reason at all."""
    lines = ask_agent.render(refused_then_grounded(CLAIM_REVIEW_REFUSAL)).splitlines()

    step = next(
        i for i, line in enumerate(lines) if "2  synthesize_cited_answer" in line
    )
    reason = reason_under(lines, step)
    assert lines[step].endswith("the agent drafted again")
    assert reason == (
        "draft refused: a claim no cited record supports. The check's reason: Features "
        'and warranty are supported, but calling it "the chair for your setup" asserts '
        "a fit with the other products that no source establishes."
    )
    assert len(lines[step + 1]) > 80, "the reason wraps at the terminal's width"
    assert max(len(line) for line in lines) <= ask_agent.LINE_CHARS
    assert (
        "passage 1" not in "\n".join(lines) and "remove the unsupported" not in reason
    )


def test_a_refusal_the_next_draft_is_not_told_about_does_not_claim_it_is():
    told = ask_agent._after_refusal(CLAIM_REVIEW_REFUSAL)
    untold = ask_agent._after_refusal(
        "Synthesis failed with AnswerabilityError: answerability: incomplete review"
    )

    assert told == "The agent is told why and drafts again."
    assert untold == "The agent drafts again."


def test_a_long_refused_claim_is_shortened_to_fit_the_terminal():
    claim = "works with " + "every laptop you might own " * 8
    text = ask_agent.render(
        refused_then_grounded(
            "Synthesis failed with SynthesisOutputError: unsupported compatibility claim "
            f"'{claim}' in: - It {claim}."
        )
    )

    assert max(len(line) for line in text.splitlines()) <= ask_agent.LINE_CHARS
    assert "draft refused: it claimed 'works with every laptop" in text


# ---------------------------------------------------------------- layout, Next and colour


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def colour_capable(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("MOSAIC_RUN_BY", raising=False)


def test_a_blank_line_comes_before_each_heading_and_before_the_outcome():
    text = ask_agent.render(grounded())

    blocks = text.split("\n\n")
    assert [block.splitlines()[0] for block in blocks] == [
        "ANSWER",
        "PLAN",
        "TOOL TRACE",
        "PRODUCTS",
        "CITATIONS",
        "OUTCOME: grounded",
    ]
    assert blocks[-1].splitlines()[-1] == f"Run ID: {RUN}"
    assert "\n\n\n" not in text and not text.startswith("\n")


def test_a_declined_answer_keeps_its_reason_with_the_outcome():
    blocks = ask_agent.render(declined()).split("\n\n")

    assert blocks[-1].splitlines() == [
        "OUTCOME: declined",
        "DECLINE REASON: unsupported_requirements",
        f"Run ID: {RUN}",
    ]


def streamed(monkeypatch, run):
    monkeypatch.setattr(
        ask_agent,
        "urlopen",
        lambda *_a, **_k: FakeStream(
            stage("understand", "Interpret request"), ("complete", {"response": run})
        ),
    )


def test_an_answer_ends_with_a_blank_line_and_the_next_step(monkeypatch, capsys):
    from service.lab_checks import mission_for_lab
    from service.participant_commands import (
        ask_100w_command,
        grade_setup_run_command,
    )

    streamed(monkeypatch, grounded())

    assert ask_agent.main([mission_for_lab(3)["query"]]) == 0

    out = capsys.readouterr().out
    assert "\n\n\n" not in out and not out.startswith("\n")
    assert out.endswith(
        f"\n\nNext: ask whether the ViewSonic meets a new need for 100W charging:\n"
        f"{ask_100w_command()}\nthen check completion with:\n"
        f"{grade_setup_run_command()}\n"
    )


def test_a_setup_answer_after_a_saved_100w_answer_goes_straight_to_the_check(
    monkeypatch, capsys
):
    """Asking the setup request again must not send anyone to the 100W question again."""
    from service.lab_checks import mission_for_lab
    from service.participant_commands import ask_100w_command, grade_setup_run_command

    streamed(monkeypatch, grounded())
    monkeypatch.setattr(ask_agent, "follow_up_saved_now", lambda: True)

    assert ask_agent.main([mission_for_lab(3)["query"]]) == 0

    out = capsys.readouterr().out
    assert out.endswith(f"\n\nNext: check completion:\n{grade_setup_run_command()}\n")
    assert ask_100w_command() not in out


def test_the_100w_question_is_followed_by_the_completion_check(monkeypatch, capsys):
    from service.participant_commands import (
        ask_100w_command,
        grade_setup_run_command,
    )

    streamed(monkeypatch, declined())
    question = ask_100w_command().removeprefix('uv run python scripts/ask_agent.py "')

    assert ask_agent.main([question.removesuffix('"')]) == 0

    assert capsys.readouterr().out.endswith(
        f"\n\nNext: check completion on your newest setup run:\n"
        f"{grade_setup_run_command()}\n"
    )


def test_a_declined_setup_request_is_asked_again_not_followed_up(monkeypatch, capsys):
    from service.lab_checks import mission_for_lab
    from service.participant_commands import ask_100w_command, ask_setup_command

    streamed(monkeypatch, declined())

    assert ask_agent.main([mission_for_lab(3)["query"]]) == 0

    out = capsys.readouterr().out
    assert out.endswith(f"again:\n{ask_setup_command()}\n")
    assert ask_100w_command() not in out


def test_a_failed_request_ends_with_a_next_that_asks_again(monkeypatch, capsys):
    from urllib.error import URLError

    def unreachable(*_args, **_kwargs):
        raise URLError("refused")

    monkeypatch.setattr(ask_agent, "urlopen", unreachable)

    assert ask_agent.main(["Find headphones for calls"]) == 1

    assert capsys.readouterr().err.endswith(
        "\n\nNext: fix what the message above names, then run this again:\n"
        'uv run python scripts/ask_agent.py "Find headphones for calls"\n'
    )


def test_a_question_that_is_too_short_ends_with_an_example(capsys):
    assert ask_agent.main(["hi"]) == 2

    err = capsys.readouterr().err
    assert err.endswith('Find headphones for calls"\n')
    assert "\n\nNext: " in err


def test_the_tool_trace_and_outcome_are_coloured_on_a_terminal(
    colour_capable, monkeypatch
):
    from scripts.terminal_text import GREEN, RED, YELLOW

    run = grounded()
    run["trace"][0] = {**run["trace"][0], "outcome": "error"}
    monkeypatch.setattr(sys, "stdout", Terminal())

    grounded_text = ask_agent.render(run)
    declined_text = ask_agent.render(declined())
    refused_text = ask_agent.render(
        refused_then_grounded(
            "Synthesis failed with SynthesisTruncated: the model stopped at max_tokens."
        )
    )

    assert f"\033[{GREEN}msuccess\033[0m" in grounded_text
    assert f"\033[{RED}merror\033[0m" in grounded_text
    # A refused draft is the answer check working: yellow, and never a red error.
    assert f"\033[{YELLOW}mrefused\033[0m" in refused_text
    assert f"\033[{RED}m" not in refused_text
    assert f"\033[{GREEN}mOUTCOME: grounded\033[0m" in grounded_text
    assert f"\033[{YELLOW}mOUTCOME: declined\033[0m" in declined_text
    assert f"\033[{YELLOW}mdenied\033[0m" in declined_text


def test_piped_output_has_no_colour_and_the_same_words(colour_capable, monkeypatch):
    tty = Terminal()
    monkeypatch.setattr(sys, "stdout", tty)
    painted = ask_agent.render(declined())
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    plain = ask_agent.render(declined())

    assert "\033" not in plain
    assert re.sub(r"\033\[[0-9;]*m", "", painted) == plain


def test_an_answer_heading_prints_its_words_without_markdown_marks(monkeypatch):
    """The answer step writes `### What to check`; Ask Mosaic draws it as a heading."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    run = grounded()
    run["answer"] = "First claim [1].\n\n### What to check\n\n- Confirm the wattage."

    answer = ask_agent.render(run).split("\n\nPLAN")[0]

    assert answer.splitlines() == [
        "ANSWER",
        "  First claim [1].",
        "  ",
        "  What to check",
        "  ",
        "  - Confirm the wattage.",
    ]


def test_an_answer_heading_is_bold_on_a_terminal(colour_capable, monkeypatch):
    monkeypatch.setattr(sys, "stdout", Terminal())
    run = grounded()
    run["answer"] = "First claim [1].\n\n### What to check"

    assert "\n  \033[1mWhat to check\033[0m\n" in ask_agent.render(run)
