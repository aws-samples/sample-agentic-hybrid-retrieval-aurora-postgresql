"""`labs/lab2_rank/rerank_off_on.py` prints Alex's monitor page with reranking off and on."""

import importlib.util
from pathlib import Path

import pytest

from scripts.validate_lab import LabValidationError
from service.lab_checks import mission_for_lab

SCRIPT = Path(__file__).resolve().parents[1] / "labs" / "lab2_rank" / "rerank_off_on.py"
TARGET = mission_for_lab(2)["target_product_ids"][0]


def _load():
    spec = importlib.util.spec_from_file_location("rerank_off_on", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


off_on = _load()


def page(titles, *, status, total, rerank_ms=None, target_at=None):
    stages = {} if rerank_ms is None else {"rerank": rerank_ms}
    results = [
        {"product_id": TARGET if index == target_at else 1000 + index, "title": title}
        for index, title in enumerate(titles)
    ]
    return {
        "results": results,
        "diagnostics": {
            "rerank_status": status,
            "total_latency_ms": total,
            "stage_timings_ms": stages,
        },
    }


OFF = page(
    ["Portable 15.6 inch monitor", "Dell Full HD 24"], status="disabled", total=295
)
ON = page(
    ["Dell UltraSharp U2720Q", "ViewSonic VG2756-4K 27 inch 4K UHD monitor with USB-C"],
    status="applied",
    total=921,
    rerank_ms=623.4,
    target_at=1,
)


def test_both_pages_print_side_by_side_with_the_target_starred():
    text = off_on.render(OFF, ON, TARGET)

    assert " 1 | Portable 15.6 inch monitor | Dell UltraSharp U2720Q" in text
    assert "| * ViewSonic VG2756-4K 27 inch 4K UHD mo…" in text
    assert all(line == line.rstrip() for line in text.splitlines())
    assert f"* = product {TARGET}, the monitor Lab 2 checks" in text


def test_the_timing_table_shows_the_reranking_step_only_when_it_ran():
    lines = off_on.render(OFF, ON, TARGET).splitlines()

    assert lines[0].split("|")[1:] == [" Reranking off ", " Reranking on"]
    assert "disabled" in lines[2] and "applied" in lines[2]
    assert "295 ms" in lines[3] and "921 ms" in lines[3]
    assert lines[4].split("|")[1].strip() == "-"
    assert lines[4].split("|")[2].strip() == "623 ms"


def test_the_two_requests_differ_only_in_rerank_and_send_shops_page_size(
    monkeypatch, capsys
):
    calls = []

    def fake_request(base_url, path, payload=None):
        calls.append((path, payload))
        return ON if payload["rerank"] else OFF

    monkeypatch.setattr(off_on, "_request", fake_request)
    code = off_on.main([])

    assert code == 0
    assert [path for path, _ in calls] == ["/api/search", "/api/search"]
    (_, without), (_, with_) = calls
    assert {**without, "rerank": True} == with_
    assert without["rerank"] is False
    assert "limit" not in without, "Shop sends no limit; the API default is its page"
    assert without["query"] == mission_for_lab(2)["query"]
    assert "Without reranking" in capsys.readouterr().out


def test_a_failed_search_is_reported_and_exits_non_zero(monkeypatch, capsys):
    def failing(*_args, **_kwargs):
        raise LabValidationError("/api/search returned HTTP 503: reranker unavailable")

    monkeypatch.setattr(off_on, "_request", failing)

    assert off_on.main([]) == 1
    assert "HTTP 503" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--help"]])
def test_help_names_the_purpose(argv, capsys):
    with pytest.raises(SystemExit):
        off_on.main(argv)
    assert "reranking off, then on" in capsys.readouterr().out
