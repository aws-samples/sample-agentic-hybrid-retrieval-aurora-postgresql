"""The terminal and the browser quote the same line of a cited record.

`data/cited_line_cases.json` is shared with `ui/src/components/ask-mosaic/quoteLines.test.ts`,
so a change to either picker that the other does not make fails one of the two suites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ask_agent
from scripts.cited_lines import cited_excerpt, clip_around
from service.synthesis import UNIT_ALIASES

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "data/cited_line_cases.json").read_text(encoding="utf-8"))
UI_UNITS = ROOT / "ui/src/components/ask-mosaic/unitAliases.json"


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["name"])
def test_each_shared_case_quotes_the_cited_line(case):
    record = CASES["records"][case["record"]]
    excerpt = cited_excerpt(record["quote"], case["answer"], case["number"])

    assert excerpt.line == case["line"]
    assert [excerpt.line[start:end] for start, end in excerpt.marks] == case["marked"]
    assert excerpt.unstated == case["unstated"]


def test_the_browser_counts_units_as_the_answer_check_does():
    """Ask Mosaic reads a JSON copy of the server's units; a drifted copy picks other lines."""
    assert json.loads(UI_UNITS.read_text(encoding="utf-8")) == UNIT_ALIASES


def test_a_long_line_keeps_its_figure_in_view():
    line = CASES["cases"][0]["line"]
    marks = [(line.index("90W"), line.index("90W") + 3)]

    shown = clip_around(line, marks, 92)

    assert shown == (
        "…USB-C connectivity for fast data, audio and video transfer, 90W charging over one cable"
    )
    assert len(shown) <= 92
    # Without a figure to keep, the line is cut at its end, as before.
    assert clip_around(line, [], 92).startswith("DITCH THE DOCK:")


def test_a_short_line_is_left_whole():
    assert clip_around("Charges a laptop at 90 W over USB-C.", [(20, 24)], 92) == (
        "Charges a laptop at 90 W over USB-C."
    )


def test_the_terminal_prints_the_cited_line_not_the_record_title(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    case = CASES["cases"][0]
    record = CASES["records"][case["record"]]
    citation = {
        "number": 1,
        "evidence_type": record["evidence_type"],
        "product_id": 1551237,
        "source_uri": "s3://catalog/meta_Electronics.jsonl",
        "revision": "fdb89c37616d7786910e76adc6e4ff043629265c4027551359e783338b2f30a0",
        "quote": record["quote"],
    }

    lines = ask_agent._citations({"answer": case["answer"], "citations": [citation]})

    assert "Title:" not in lines[1] and "90W" in lines[1]


def test_the_terminal_names_a_figure_the_record_never_states(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    record = CASES["records"]["viewsonic_listing"]
    citation = {
        "number": 1,
        "evidence_type": "product_spec",
        "product_id": 1551237,
        "source_uri": "s3://catalog/meta_Electronics.jsonl",
        "revision": "fdb89c37616d",
        "quote": record["quote"],
    }
    answer = "Its listing states 90W, short of the 100W this laptop needs [1]."

    lines = ask_agent._citations({"answer": answer, "citations": [citation]})

    assert lines[-1].strip() == "No line in this record states 100W."
