"""Run Alex's monitor request with reranking off, then on, and print both pages.

    uv run python labs/lab2_rank/rerank_off_on.py

Both calls send Lab 2's saved request and filters through the API Shop uses, for
the page Shop shows; the only difference is `rerank`. Each call runs retrieval
again, so read the two lists before crediting every difference to reranking.
Nothing Shop serves changes; each search is saved like any other.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lab_terminal import request_payload
from scripts.validate_lab import LabValidationError, _request
from service.lab_checks import mission_for_lab

TITLE_CHARS = 40


def _row(cells: list[str], widths: list[int]) -> str:
    padded = (cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
    return (" " + " | ".join(padded)).rstrip()


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """A psql-style table: the header, a rule, then one line per row."""
    widths = [
        max(len(cell) for cell in column) for column in zip(header, *rows, strict=True)
    ]
    rule = "-" + "-+-".join("-" * width for width in widths) + "-"
    return [_row(header, widths), rule, *(_row(row, widths) for row in rows)]


def _timing(response: dict[str, Any]) -> list[str]:
    diagnostics = response["diagnostics"]
    step = diagnostics.get("stage_timings_ms", {}).get("rerank")
    return [
        diagnostics["rerank_status"],
        f"{diagnostics['total_latency_ms']} ms",
        "-" if step is None else f"{step:.0f} ms",
    ]


def _title(response: dict[str, Any], index: int, target: int) -> str:
    results = response["results"]
    if index >= len(results):
        return ""
    item = results[index]
    title = ("* " if item["product_id"] == target else "") + item["title"]
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1] + "…"


def render(off: dict[str, Any], on: dict[str, Any], target: int) -> str:
    """The timing of both searches, then their pages side by side."""
    timing_off, timing_on = _timing(off), _timing(on)
    timing = table(
        ["", "Reranking off", "Reranking on"],
        [
            [label, timing_off[index], timing_on[index]]
            for index, label in enumerate(("Status", "Search time", "Reranking step"))
        ],
    )
    count = max(len(off["results"]), len(on["results"]))
    pages = table(
        ["#", "Without reranking", "With reranking"],
        [
            [f"{index + 1:>2}", _title(off, index, target), _title(on, index, target)]
            for index in range(count)
        ],
    )
    legend = f"* = product {target}, the monitor Lab 2 checks"
    return "\n".join([*timing, "", *pages, legend])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    mission = mission_for_lab(2)
    payload = request_payload(mission)
    # Shop sends no limit, so the API's default is the page Shop shows.
    del payload["limit"]
    pages = {}
    try:
        for rerank in (False, True):
            pages[rerank] = _request(
                args.api_url, "/api/search", {**payload, "rerank": rerank}
            )
    except LabValidationError as error:
        print(f"Search failed: {error}", file=sys.stderr)
        return 1
    print(render(pages[False], pages[True], mission["target_product_ids"][0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
