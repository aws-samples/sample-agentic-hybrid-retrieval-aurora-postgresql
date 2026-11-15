"""`scripts/read_citation.py` shows the whole record behind one citation of a saved run."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from scripts import read_citation
from service import db

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "data/cited_line_cases.json").read_text())
RUN_ID = UUID("794c29f6-b200-4ae4-8fc7-856c3fd9c5a5")
ANSWER = (
    "The ViewSonic VG2756-4K's integrated USB hub connects and charges peripherals over a "
    "single cable [1]. Its listing states 90W charging over one cable [1], below the 100W "
    "this laptop needs. A reviewer reports passing battery charging to their laptop [2]."
)


def citation(number, evidence_type, record):
    return {
        "number": number,
        "evidence_id": 900 + number,
        "evidence_type": evidence_type,
        "product_id": 1551237,
        "source_uri": "https://example.test/amazon-reviews-2023/meta_Electronics.jsonl",
        "revision": "fdb89c37616dabcdef0123456789",
        "title": "ViewSonic VG2756-4K",
        "quote": CASES["records"][record]["quote"],
        "rating": None,
    }


def run(outcome="grounded", citations="default"):
    return {
        "agent_turn_id": RUN_ID,
        "user_message": "My laptop needs 100W charging.",
        "assistant_message": ANSWER if outcome == "grounded" else None,
        "created_at": datetime(2026, 11, 15, 0, 28, 3, tzinfo=UTC),
        "outcome": outcome,
        "citations": [
            citation(1, "product_spec", "viewsonic_listing"),
            citation(2, "customer_review", "viewsonic_review"),
        ]
        if citations == "default"
        else citations,
    }


class Connection:
    def __init__(self, row):
        self.row = row
        self.params = None

    def execute(self, sql, params):
        self.sql, self.params = sql, params
        return self

    def fetchone(self):
        return self.row


def use(monkeypatch, row):
    connection = Connection(row)

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(db, "connect", connect)
    return connection


def test_it_prints_every_sentence_citing_the_number_and_marks_the_quoted_line(
    monkeypatch, capsys
):
    connection = use(monkeypatch, run())

    assert read_citation.main(["1", "--run-id", str(RUN_ID)]) == 0

    out = capsys.readouterr().out
    assert connection.params == {"run_id": RUN_ID}
    assert "THE ANSWER'S SENTENCES THAT CITE [1]" in out
    assert "integrated USB hub connects and charges peripherals" in out
    assert "Its listing states 90W charging over one cable [1]" in out
    assert "reviewer reports passing battery" not in out, "[2]'s sentence is not [1]'s"
    assert out.count("»") == 2, "the legend and exactly one record line"
    marked = " ".join(out.split("\n  » ", 1)[1].split("\n    ")[:2])
    assert (
        marked.startswith("DITCH THE DOCK") and "90W charging over one cable" in marked
    )
    assert "Categories: Electronics > Computers & Accessories > Monitors" in out
    assert "Description:" not in out
    assert "[1] product_spec  1551237  meta_Electronics.jsonl @ fdb89c37616d" in out
    assert out.rstrip().endswith(read_citation.read_citation_command("2", str(RUN_ID)))


def test_a_review_citation_reads_the_review_whole(monkeypatch, capsys):
    use(monkeypatch, run())

    assert read_citation.main(["2", "--run-id", str(RUN_ID)]) == 0

    out = capsys.readouterr().out
    assert "I've been using this for about a month" in out
    assert out.rstrip().endswith(read_citation.read_citation_command("1", str(RUN_ID)))


@pytest.mark.parametrize(
    ("row", "number", "expected"),
    [
        (None, 1, "no saved run has the ID"),
        (
            run(outcome="declined", citations=None),
            1,
            "has no cited answer (OUTCOME: declined)",
        ),
        (run(), 3, "cites [1], [2], not [3]"),
    ],
)
def test_a_run_without_that_citation_names_the_way_out(
    monkeypatch, capsys, row, number, expected
):
    use(monkeypatch, row)

    assert read_citation.main([str(number), "--run-id", str(RUN_ID)]) == 2

    err = capsys.readouterr().err
    assert expected in err
    assert "\n\nNext: " in err


def test_without_a_run_id_it_reads_the_setup_run_completion_grades(monkeypatch, capsys):
    """A later question from Ask Mosaic or Playground must not take the graded run's place."""
    connection = use(monkeypatch, run())
    monkeypatch.setattr(
        read_citation, "graded_setup_run_id", lambda _connection: RUN_ID
    )

    assert read_citation.main(["1"]) == 0

    assert connection.params == {"run_id": RUN_ID}
    out = capsys.readouterr().out
    assert out.startswith(f"Run {RUN_ID}")
    assert "Alex's setup run, the one completion grades." in out.splitlines()[1]
    assert out.rstrip().endswith(f"read_citation.py 2 --run-id {RUN_ID}"), (
        "Next pins the run"
    )


def test_a_named_run_does_not_claim_to_be_the_graded_one(monkeypatch, capsys):
    use(monkeypatch, run())
    monkeypatch.setattr(
        read_citation,
        "graded_setup_run_id",
        lambda _c: pytest.fail("looked up the default"),
    )

    assert read_citation.main(["1", "--run-id", str(RUN_ID)]) == 0

    assert "completion grades" not in capsys.readouterr().out


def test_with_no_setup_run_it_names_the_setup_request(monkeypatch, capsys):
    use(monkeypatch, None)
    monkeypatch.setattr(read_citation, "graded_setup_run_id", lambda _connection: None)

    assert read_citation.main(["1"]) == 2

    err = capsys.readouterr().err
    assert "found no answer to Alex's setup request since Lab 3 started" in err
    assert read_citation.ask_setup_command() in err


def test_the_default_is_the_graders_own_pick(monkeypatch):
    """The reader asks `grade_setup_run.pick_setup_run`, not a rule of its own."""
    from scripts import grade_setup_run

    seen = {}

    def pick(connection, request, started_at, follow_up):
        seen.update(request=request, follow_up=follow_up)
        return grade_setup_run.SetupRunPick(run={"agent_turn_id": RUN_ID})

    monkeypatch.setattr(grade_setup_run, "pick_setup_run", pick)
    monkeypatch.setattr("service.agent_deploys.lab_3_started_at", lambda _root: None)

    assert read_citation.graded_setup_run_id(object()) == RUN_ID
    assert "Steelcase Gesture" in seen["request"] and "100W" in seen["follow_up"]


def test_a_quote_inside_a_paragraph_starts_its_own_marked_line():
    paragraph = "Opening words of the listing. The quoted sentence states 90W charging. Closing words."
    quote = {
        **citation(1, "product_spec", "viewsonic_listing"),
        "quote": f"Title: Dock\n{paragraph}",
    }
    answer = "It supports 90W charging [1]."

    out = read_citation.render({**run(), "assistant_message": answer}, quote)

    body = out[
        out.index(next(line for line in out if line.startswith("THE WHOLE RECORD")))
        + 1 :
    ]
    assert body == [
        "    Dock",
        "    Opening words of the listing.",
        "  » The quoted sentence states 90W charging.",
        "    Closing words.",
    ]


def test_the_record_keeps_every_line_and_reads_markup_as_the_site_shows_it():
    lines = read_citation.record_lines(
        "Title: Example Dock\n\nCategories: Electronics > Docks\n\nDescription:\n"
        "[[VIDEOID:abc]] Works with my old [[ASIN:B0TEST Example Laptop]].<br />Charges at 90W."
    )

    assert lines == [
        "Example Dock",
        "Categories: Electronics > Docks",
        "Works with my old Example Laptop.",
        "Charges at 90W.",
    ]


@pytest.mark.parametrize("named", [None, RUN_ID])
def test_an_unreachable_aurora_names_a_retry_of_the_same_command(
    monkeypatch, capsys, named
):
    import psycopg

    @contextmanager
    def connect():
        raise psycopg.OperationalError("connection timeout expired")
        yield

    monkeypatch.setattr(db, "connect", connect)
    argv = ["3"] + (["--run-id", str(named)] if named else [])

    assert read_citation.main(argv) == 2

    err = capsys.readouterr().err
    assert err.startswith("Citation rule: Aurora did not answer (OperationalError).")
    assert "Traceback" not in err and "tell your facilitator" in err
    pinned = str(named) if named else None
    assert err.rstrip().endswith(read_citation.read_citation_command("3", pinned))


@pytest.mark.parametrize(
    ("record", "said"),
    [
        ("{", "the saved start of Lab 3 cannot be read (JSONDecodeError)"),
        ('{"version": 1, "lab": 2}', "is not a Lab 3 start record"),
    ],
)
def test_an_unreadable_lab_3_start_record_names_its_reset(
    monkeypatch, capsys, tmp_path, record, said
):
    from scripts import grade_setup_run

    started = tmp_path / ".local" / "lab-3" / "start.json"
    started.parent.mkdir(parents=True)
    started.write_text(record)
    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    use(monkeypatch, run())

    assert read_citation.main(["1"]) == 2

    err = capsys.readouterr().err
    assert err.startswith("Citation rule: ") and said in err
    assert "lab_state.py reset --lab 3" in err and "Traceback" not in err
