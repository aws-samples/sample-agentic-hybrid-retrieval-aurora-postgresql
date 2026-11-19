"""`scripts/read_citation.py` shows the whole record behind one citation of a saved run."""

import hashlib
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
STARTED = datetime(2026, 11, 15, 0, 10, tzinfo=UTC)
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


def started(monkeypatch, at=STARTED):
    """Lab 3's start time as the reader reads it, without a start record on disk."""
    monkeypatch.setattr("service.agent_deploys.lab_3_started_at", lambda _root: at)


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
    assert out.count("»") == 3, (
        "the legend, exactly one record line and the closing repeat"
    )
    assert "(» Suggested line to inspect)" in out
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
    started(monkeypatch)
    picked = []

    def pick(_connection, started_at):
        picked.append(started_at)
        return RUN_ID

    monkeypatch.setattr(read_citation, "graded_setup_run_id", pick)

    assert read_citation.main(["1"]) == 0

    assert connection.params == {"run_id": RUN_ID}
    assert picked == [STARTED], "picked from runs since Lab 3 started"
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
        lambda *_a: pytest.fail("looked up the default"),
    )

    assert read_citation.main(["1", "--run-id", str(RUN_ID)]) == 0

    assert "completion grades" not in capsys.readouterr().out


def test_with_no_setup_run_it_names_the_setup_request(monkeypatch, capsys):
    use(monkeypatch, None)
    started(monkeypatch)
    monkeypatch.setattr(read_citation, "graded_setup_run_id", lambda *_a: None)

    assert read_citation.main(["1"]) == 2

    err = capsys.readouterr().err
    assert "found no answer to Alex's setup request since Lab 3 started" in err
    assert read_citation.ask_setup_command() in err


def test_the_default_is_the_graders_own_pick(monkeypatch):
    """The reader asks `grade_setup_run.pick_setup_run`, not a rule of its own."""
    from scripts import grade_setup_run

    seen = {}

    def pick(connection, request, started_at, follow_up):
        seen.update(request=request, started_at=started_at, follow_up=follow_up)
        return grade_setup_run.SetupRunPick(run={"agent_turn_id": RUN_ID})

    monkeypatch.setattr(grade_setup_run, "pick_setup_run", pick)

    assert read_citation.graded_setup_run_id(object(), STARTED) == RUN_ID
    assert "Steelcase Gesture" in seen["request"] and "100W" in seen["follow_up"]
    assert seen["started_at"] == STARTED


def test_a_quote_inside_a_paragraph_starts_its_own_marked_line():
    paragraph = "Opening words of the listing. The quoted sentence states 90W charging. Closing words."
    quote = {
        **citation(1, "product_spec", "viewsonic_listing"),
        "quote": f"Title: Dock\n{paragraph}",
    }
    answer = "It supports 90W charging [1]."

    out = read_citation.render({**run(), "assistant_message": answer}, quote)

    start = out.index(next(line for line in out if line.startswith("THE WHOLE RECORD")))
    body = out[start + 2 : out.index("", start)]
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
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        yield

    monkeypatch.setattr(db, "connect", connect)
    started(monkeypatch)
    argv = ["3"] + (["--run-id", str(named)] if named else [])

    assert read_citation.main(argv) == 2

    err = capsys.readouterr().err
    assert err.startswith("Citation rule: Aurora did not answer (timed out).")
    assert "Traceback" not in err and "tell your facilitator" in err
    pinned = str(named) if named else None
    assert err.rstrip().endswith(read_citation.read_citation_command("3", pinned))


@pytest.mark.parametrize(
    "record",
    ["{", '{"version": 1, "lab": 2}', '{"version": 7, "lab": 3}', "[]"],
)
def test_an_unreadable_lab_3_start_record_points_to_the_run_id_not_a_reset(
    monkeypatch, capsys, tmp_path, record
):
    """A reset would discard agent.py; the Run ID reads the same saved answer without it."""
    from scripts import grade_setup_run

    started = tmp_path / ".local" / "lab-3" / "start.json"
    started.parent.mkdir(parents=True)
    started.write_text(record)
    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    use(monkeypatch, run())

    assert read_citation.main(["1"]) == 2

    err = capsys.readouterr().err
    assert err.startswith("Citation rule: the saved start of Lab 3 cannot be read")
    assert "reset" not in err and "Traceback" not in err
    assert err.rstrip().endswith(read_citation.read_citation_command("1", "RUN_ID"))


@pytest.mark.parametrize("named", [None, RUN_ID])
def test_an_empty_database_setting_names_the_terminal_not_the_start_record(
    monkeypatch, capsys, named
):
    """With the Run ID already given, advice to give it would loop."""
    from service.db import DatabaseNotConfigured

    @contextmanager
    def connect():
        raise DatabaseNotConfigured("DATABASE_URL is not configured")
        yield

    monkeypatch.setattr(db, "connect", connect)
    started(monkeypatch)
    argv = ["1"] + (["--run-id", str(named)] if named else [])

    assert read_citation.main(argv) == 2

    err = capsys.readouterr().err
    assert err.startswith(
        "Citation rule: DATABASE_URL is empty in this terminal, so Aurora cannot be "
        "reached."
    )
    assert "start of Lab 3" not in err and "open a new terminal" in err
    pinned = str(named) if named else None
    assert err.rstrip().endswith(read_citation.read_citation_command("1", pinned))


def test_before_lab_3_starts_no_run_is_called_the_graded_one(monkeypatch, capsys):
    """Completion refuses a run from before the start, so the reader cannot pick one."""
    monkeypatch.setattr(
        db, "connect", lambda: pytest.fail("a run picked before the start is refused")
    )
    started(monkeypatch, None)

    assert read_citation.main(["1"]) == 2

    err = capsys.readouterr().err
    assert err.startswith("Citation rule: Lab 3 has not started")
    assert err.rstrip().endswith(read_citation.read_citation_command("1", "RUN_ID"))


def test_before_lab_3_starts_a_named_run_still_reads(monkeypatch, capsys):
    use(monkeypatch, run())
    started(monkeypatch, None)

    assert read_citation.main(["1", "--run-id", str(RUN_ID)]) == 0

    out = capsys.readouterr().out
    assert out.startswith(f"Run {RUN_ID}") and "completion grades" not in out


def test_it_ends_with_the_sentence_and_the_quoted_line_so_a_long_record_hides_neither():
    paragraph = "The quoted sentence states 90W charging."
    quote = {
        **citation(1, "product_spec", "viewsonic_listing"),
        "quote": "Title: Dock\n"
        + "\n".join(f"Feature line {n}." for n in range(60))
        + f"\n{paragraph}\nLast line.",
    }
    answer = "It supports 90W charging [1]. Its reviewer liked it [2]."

    out = read_citation.render({**run(), "assistant_message": answer}, quote)

    assert out[-4:] == [
        "",
        "TO JUDGE: THE SENTENCE CITING [1] AND A SUGGESTED LINE TO INSPECT",
        "  It supports 90W charging [1].",
        "  » The quoted sentence states 90W charging.",
    ]


CAPTURED_ANSWER = (
    "ViewSonic VG2756-4K's listing describes a 27-inch 4K IPS docking monitor with USB-C, "
    "Ethernet and a 40-degree tilt [3]."
)


def reviewed(answer, passages):
    """The claim-support receipt `synthesis` saves for an answer, as Aurora returns it."""
    return {
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "passages": [
            {"id": i, "verdict": v, "support": s, "reason": "checked"}
            for i, v, s in passages
        ],
    }


def listing_run(answer, review=None):
    return {**run(), "assistant_message": answer, "claim_review": review}


def marked_lines(out):
    return [line for line in out if line.startswith("  » ")]


def test_a_paraphrase_is_not_called_the_quoted_line_when_nothing_was_saved():
    """Recorded run 49fc8c0f: a 27-inch 4K IPS USB-C Ethernet tilt claim, tilt line marked."""
    listing = citation(3, "product_spec", "viewsonic_listing")

    out = read_citation.render(listing_run(CAPTURED_ANSWER), {**listing, "number": 3})
    text = "\n".join(out)

    assert "(» Suggested line to inspect)" in text
    assert "TO JUDGE: THE SENTENCE CITING [3] AND A SUGGESTED LINE TO INSPECT" in out
    assert "the line the answer's quote comes from" not in text
    assert "THE LINE IT QUOTES" not in text and "saved supporting passage" not in text
    assert marked_lines(out)[0].startswith("  » A best-in-class ergonomic design")


def saved_review_render(passages, answer=CAPTURED_ANSWER, receipt_answer=None):
    listing = citation(3, "product_spec", "viewsonic_listing")
    review = reviewed(receipt_answer or answer, passages)
    return read_citation.render(listing_run(answer, review), listing)


def test_a_saved_supporting_quote_is_marked_instead_of_the_suggestion():
    quote = "27” 4K Ultra HD docking monitor"
    out = saved_review_render([(1, "supported", [{"number": 3, "quote": quote}])])
    text = "\n".join(out)

    assert "(» The answer check's saved supporting passage)" in text
    assert "AND THE ANSWER CHECK'S SAVED SUPPORTING PASSAGE" in text
    assert "Suggested line to inspect" not in text
    assert marked_lines(out)[0] == f"  » {quote}"
    assert marked_lines(out)[-1] == f"  » {quote}", "repeated under TO JUDGE"
    assert not any("40-degree tilt and bi-directional" in x for x in marked_lines(out))
    assert "    Designed to boost productivity" in text, (
        "the rest of the paragraph stays"
    )


def test_every_saved_quote_for_the_number_is_marked_so_support_can_span_lines():
    quotes = [
        "27” 4K Ultra HD docking monitor",
        "40-degree tilt and bi-directional pivot",
    ]
    out = saved_review_render(
        [(1, "supported", [{"number": 3, "quote": q} for q in quotes])]
    )

    assert [x.strip("» ") for x in marked_lines(out)[:2]] == quotes
    assert len(marked_lines(out)) == 4


@pytest.mark.parametrize(
    "case",
    [
        "repeated",
        "across_lines",
        "missing",
        "other_answer",
        "other_number",
        "unsupported",
    ],
)
def test_a_saved_quote_that_cannot_be_placed_falls_back_to_the_suggestion(case):
    quote = {
        "repeated": "4K",
        "across_lines": "Listing features: VERSATILE MONITOR",
        "missing": "a quote the record never says",
    }.get(case, "27” 4K Ultra HD docking monitor")
    number = 2 if case == "other_number" else 3
    verdict = "unsupported" if case == "unsupported" else "supported"
    out = saved_review_render(
        [(1, verdict, [{"number": number, "quote": quote}])],
        receipt_answer="A different answer [3]." if case == "other_answer" else None,
    )
    text = "\n".join(out)

    assert "(» Suggested line to inspect)" in text
    assert "saved supporting passage" not in text
    assert marked_lines(out)[0].startswith("  » A best-in-class ergonomic design")


def test_a_quote_saved_for_a_passage_that_does_not_cite_the_number_is_ignored():
    answer = "It has a 40-degree tilt [3]. It charges its peripherals [1]."
    out = saved_review_render(
        [
            (
                1,
                "supported",
                [{"number": 3, "quote": "27” 4K Ultra HD docking monitor"}],
            ),
            (2, "supported", [{"number": 3, "quote": "single-cable simplicity"}]),
        ],
        answer=answer,
    )

    assert marked_lines(out)[0].startswith("  » 27” 4K Ultra HD docking monitor")
    assert not any("single-cable" in x for x in marked_lines(out))


def test_a_run_row_without_the_saved_review_still_renders():
    """Runs saved before the review kept quotes have no claim_review key at all."""
    out = read_citation.render(run(), run()["citations"][0])

    assert any("Suggested line to inspect" in line for line in out)


def test_saved_run_reads_the_claim_review_from_the_turn():
    connection = Connection(None)

    read_citation.saved_run(connection, RUN_ID)

    assert "claim_review" in connection.sql


DELIVERY_REVIEW = (
    "Arrived two days early and the box was dented. The delivery driver was polite."
)


def review_citation(title, body=DELIVERY_REVIEW):
    return {
        **citation(2, "customer_review", "viewsonic_review"),
        "title": title,
        "quote": body,
    }


def review_render(
    title, passages, answer="Reviewers call it comfortable for shifts [2]."
):
    review = reviewed(answer, passages)
    return read_citation.render(listing_run(answer, review), review_citation(title))


def test_a_review_title_is_shown_and_marked_when_the_answer_check_quoted_it():
    """The check accepts a quote from a title; the body is about delivery."""
    out = review_render(
        "Comfortable for long shifts",
        [(1, "supported", [{"number": 2, "quote": "Comfortable for long shifts"}])],
    )
    text = "\n".join(out)

    assert "THE WHOLE RECORD (» The answer check's saved supporting passage)" in text
    assert marked_lines(out)[0] == "  » Review title: Comfortable for long shifts"
    assert not any("delivery driver" in x for x in marked_lines(out))
    assert "    Arrived two days early" in text, "the body follows the title"
    body = "    Arrived two days early and the box was dented. The delivery driver was polite."
    assert out.index("  » Review title: Comfortable for long shifts") < out.index(body)


def test_a_partial_title_quote_marks_only_those_words_after_the_label():
    out = review_render(
        "Comfortable for long shifts",
        [(1, "supported", [{"number": 2, "quote": "long shifts"}])],
    )

    assert "    Review title: Comfortable for" in out
    assert marked_lines(out)[0] == "  » long shifts"


def test_a_review_without_a_saved_quote_still_shows_its_title_and_suggests_a_line():
    out = read_citation.render(
        listing_run("Reviewers call it comfortable [2]."),
        review_citation("Comfortable for long shifts"),
    )

    assert "    Review title: Comfortable for long shifts" in out
    assert "THE WHOLE RECORD (» Suggested line to inspect)" in "\n".join(out)


def test_a_review_with_no_title_adds_no_title_line():
    out = read_citation.render(
        listing_run("Reviewers call it comfortable [2]."), review_citation("")
    )

    assert not any("Review title" in line for line in out)


def test_a_listings_title_is_printed_once():
    listing = citation(1, "product_spec", "viewsonic_listing")
    title = "ViewSonic VG2756-4K 27 Inch IPS 4K Docking Monitor"
    out = read_citation.render(listing_run(ANSWER), {**listing, "title": title})
    text = "\n".join(out)

    assert text.count("ViewSonic VG2756-4K 27 Inch IPS 4K Docking Monitor with") == 1
    assert "Review title" not in text
    assert read_citation.shown_record(listing) == listing["quote"]


def test_an_ambiguous_title_quote_falls_back():
    """The same words in the title and the body: no single place, so no saved label."""
    body = "Comfortable for long shifts, said the box. Dented."
    review = reviewed(
        "Reviewers call it comfortable [2].",
        [(1, "supported", [{"number": 2, "quote": "Comfortable for long shifts"}])],
    )

    out = read_citation.render(
        listing_run("Reviewers call it comfortable [2].", review),
        review_citation("Comfortable for long shifts", body),
    )

    assert "THE WHOLE RECORD (» Suggested line to inspect)" in "\n".join(out)
