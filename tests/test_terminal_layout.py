"""A participant command's output is grouped, ends with a Next line and is coloured on a terminal.

Each test runs the command's own entry point and reads what it printed. Aurora, the API and
the checks' verdicts are the boundaries that are substituted; the printing is as shipped.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from shutil import copy2

import pytest

from scripts import lab_entry, lab_request, lab_state
from scripts.lab_state import LABS, REPO, LabDatabaseState
from scripts.terminal_text import GREEN, RED, tidy
from service import lab_checks
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    DEPLOY_AGENT,
    LIST_TOOLS,
    load_context_command,
    open_psql_command,
    repeat_request_command,
)


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _a_colour_capable_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("MOSAIC_RUN_BY", raising=False)


def assert_well_laid_out(output: str) -> list[str]:
    """No blank line first, never two in a row; the paragraphs the output falls into."""
    assert output.strip(), "the command printed nothing"
    assert not output.startswith("\n"), f"opens with a blank line: {output[:40]!r}"
    assert "\n\n\n" not in output, "two blank lines in a row"
    assert output.endswith("\n")
    return output.rstrip("\n").split("\n\n")


def assert_ends_with_next(output: str, *snippets: str) -> str:
    """The last paragraph is a `Next:` that names every snippet; it is returned."""
    last = assert_well_laid_out(output)[-1]
    assert last.startswith("Next: "), f"last paragraph is not a Next: {last!r}"
    for snippet in snippets:
        assert snippet in last, f"{snippet!r} not in {last!r}"
    return last


# ---------------------------------------------------------------- the saved request


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Aurora and the API as boundaries: one catalog, one search whose target is missing."""
    mission = lab_checks.load_mission("retrieve")
    ready = {
        "database": {"dataset_id": mission["dataset_id"], "catalog_ready": True},
        "source": {"dataset_manifest_sha256": "hash"},
        "configured_models": {"embed": "model"},
    }
    target = mission["target_product_ids"][0]
    event = {
        "run": {
            "search_event_id": "11111111-1111-1111-1111-111111111111",
            "normalized_query": mission["query"],
            "dataset_manifest_sha256": "hash",
            "diagnostics": {"query_embedding": [0.1, 0.2, 0.3]},
            "retrieval_profile": {"rrf_k": 60},
        },
        "candidates": [{"product_id": 1}],
    }
    response = {
        "search_event_id": event["run"]["search_event_id"],
        "results": [
            {"title": "Sony WH-1000XM5", "signals": {"final_rank": 1}},
            {"title": "Bose QuietComfort 45", "signals": {"final_rank": 2}},
        ],
        "diagnostics": {"embedding_dimensions": 3},
    }

    class Connection:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return {"dataset_id": mission["dataset_id"], "catalog_sha256": "hash"}

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr("service.db.connect", connect)
    monkeypatch.setattr(
        "service.catalog_runtime.active_dataset", lambda: mission["dataset_id"]
    )
    monkeypatch.setattr(
        lab_request,
        "_request",
        lambda _url, path, *_: ready if path == "/api/readiness" else event,
    )
    monkeypatch.setattr(lab_request, "_search", lambda *_: response)
    monkeypatch.setattr(lab_request, "paired_searches", lambda *_: None)
    monkeypatch.setattr(lab_request, "ROOT", tmp_path)
    monkeypatch.setattr(lab_request, "_lab_2_hides_lab_1", lambda: False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    return {"event": event, "target": target, "output": tmp_path / ".local/lab-1"}


def _send(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["lab_request.py", "send", *argv])
    assert lab_request.main() == 0


def test_send_groups_the_results_the_target_and_the_saved_context(
    api, monkeypatch, capsys
) -> None:
    _send(monkeypatch, "--lab", "1", "--phase", "before")

    paragraphs = assert_well_laid_out(capsys.readouterr().out)

    assert paragraphs[0].startswith("Alex's request: ")
    assert " 1. Sony WH-1000XM5\n 2. Bose QuietComfort 45" in paragraphs[0]
    assert paragraphs[1].startswith(f"Target {api['target']}")
    assert paragraphs[2].startswith("Saved the application response. In psql:\n\\i ")


def test_send_after_a_saved_before_groups_target_before_and_after(
    api, monkeypatch, capsys
) -> None:
    mission = lab_checks.load_mission("retrieve")
    api["output"].mkdir(parents=True)
    (api["output"] / "before-state.json").write_text(
        json.dumps(
            {
                "request": lab_request.request_payload(mission),
                "catalog_hash": "hash",
                "models": {"embed": "model"},
                "event": api["event"],
                "run_id": "22222222-2222-2222-2222-222222222222",
            }
        )
    )

    _send(monkeypatch, "--lab", "1", "--phase", "after")

    paragraphs = assert_well_laid_out(capsys.readouterr().out)
    assert paragraphs[1].splitlines()[1] == "Before: not on the shortlist."
    assert paragraphs[-2].startswith("Saved the application response")


@pytest.mark.parametrize(
    ("lab", "phase", "snippets"),
    [
        (1, "before", [open_psql_command(1), load_context_command(1)]),
        (1, "after", [ADVANCE_TO_LAB_2]),
    ],
)
def test_send_ends_with_the_step_the_guide_gives_next(
    api, monkeypatch, capsys, lab, phase, snippets
) -> None:
    if phase == "after":
        api["output"].mkdir(parents=True)
        mission = lab_checks.load_mission("retrieve")
        (api["output"] / "before-state.json").write_text(
            json.dumps(
                {
                    "request": lab_request.request_payload(mission),
                    "catalog_hash": "hash",
                    "models": {"embed": "model"},
                    "event": api["event"],
                    "run_id": "22222222-2222-2222-2222-222222222222",
                }
            )
        )

    _send(monkeypatch, "--lab", str(lab), "--phase", phase)

    assert_ends_with_next(capsys.readouterr().out, *snippets)


def test_a_failed_send_ends_with_a_next_that_repeats_it(
    api, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        lab_request,
        "prepare",
        lambda *_: (_ for _ in ()).throw(
            lab_request.LabValidationError("the API did not answer")
        ),
    )
    monkeypatch.setattr(
        "sys.argv", ["lab_request.py", "send", "--lab", "1", "--phase", "after"]
    )

    with pytest.raises(SystemExit) as stopped:
        lab_request.main()

    message = str(stopped.value)
    assert message.splitlines()[-3:] == [
        "",
        "Next: do what the message above says, then run",
        repeat_request_command(1),
    ]


# ---------------------------------------------------------------- the hand-off


@pytest.fixture
def aurora_applied() -> dict[int, str]:
    """What Aurora runs of each SQL lab, as the applied-state read answers."""
    return {1: "applied", 2: "stale"}


@pytest.fixture
def checkout(
    api, aurora_applied, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """A copy of the lab files with Aurora, the apply and the live proof substituted."""
    repo = tmp_path / "checkout"
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = repo / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)

    @contextmanager
    def connect(_dsn):
        yield object()

    def applied(lab, _connection, **_kwargs):
        return LabDatabaseState(
            state=aurora_applied.get(lab, "not_applicable"), detail=""
        )

    def apply(_dsn, _repo, say):
        say("Applied it to Aurora.")
        return "sha"

    monkeypatch.setattr(lab_entry, "assert_workshop_database", lambda _dsn: None)
    monkeypatch.setattr(lab_entry, "_connect", connect)
    monkeypatch.setattr(lab_entry, "read_applied_sql_state", applied)
    monkeypatch.setattr(lab_entry, "_apply", apply)
    monkeypatch.setattr(lab_request, "ROOT", repo)
    return repo


@tidy
def _advance(lab: int, repo: Path) -> int:
    """`lab_state.py advance --lab N` as the participant sees it, on the copied checkout."""
    lab_entry.advance(lab, api_url="http://api", dsn="aurora", repo=repo, say=print)
    lab_state._entered_step("advance", lab)
    return 0


def test_advance_lab_1_puts_a_blank_line_between_its_parts(
    checkout, monkeypatch, capsys
) -> None:
    def validate(_url, events, *, rerun):
        events.append("verified")
        return ["Alex's mistyped ID: found by fuzzy matching", "G-001: the correct ID"]

    monkeypatch.setattr("scripts.prove_lab.prove_lab_1", validate)
    monkeypatch.setattr("scripts.prove_lab.record_completion", lambda *_: None)

    _advance(1, checkout)

    paragraphs = assert_well_laid_out(capsys.readouterr().out)
    starts = [paragraph.splitlines()[0] for paragraph in paragraphs]
    assert starts[0].startswith("Validating Lab 1 in Aurora")
    assert paragraphs[0].count("\nPASS: ") == 2
    assert starts[1:3] == [
        "Lab 1: production-path validation passed. Passing evidence saved.",
        "Preparing Lab 2: install its fault once and save the starting request.",
    ]
    assert starts[6].startswith("Lab 2: prepared. Continue with the saved failure")
    assert starts[7].startswith("Next: ")
    assert starts[3].startswith("Alex's request: ")
    assert starts[4].startswith("Target ")
    assert starts[5].startswith("Saved the application response. In psql:")
    assert "Installed Lab 2's fault" in paragraphs[2]
    assert "Applied it to Aurora." in paragraphs[2]


def test_advance_lab_1_ends_with_the_lab_2_psql_step(
    checkout, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "scripts.prove_lab.prove_lab_1", lambda _u, events, *, rerun: ["check"]
    )
    monkeypatch.setattr("scripts.prove_lab.record_completion", lambda *_: None)

    _advance(1, checkout)

    assert_ends_with_next(
        capsys.readouterr().out, open_psql_command(2), load_context_command(2)
    )


def test_advance_lab_2_ends_with_the_lab_3_editor_step(
    checkout, aurora_applied, monkeypatch, capsys
) -> None:
    lab_entry.start(
        2, api_url="http://api", dsn="aurora", repo=checkout, say=lambda _: None
    )
    lab_state.set_lab_state(2, solved=True, repo=checkout)
    capsys.readouterr()
    aurora_applied[2] = "applied"
    monkeypatch.setattr(
        "scripts.prove_lab.prove_lab_2", lambda _u, events, *, rerun: ["check"]
    )
    monkeypatch.setattr("scripts.prove_lab.record_completion", lambda *_: None)
    monkeypatch.setattr(
        "service.lab_proof.entry_check",
        lambda *_: type("Check", (), {"passed": True, "detail": ""})(),
    )

    _advance(2, checkout)

    last = assert_ends_with_next(capsys.readouterr().out, LIST_TOOLS)
    assert "labs/lab3_reason/agent.py" in last


def test_a_pass_line_is_green_on_a_terminal_and_plain_when_piped(
    checkout, monkeypatch
) -> None:
    monkeypatch.setattr(
        "scripts.prove_lab.prove_lab_1", lambda _u, events, *, rerun: ["check"]
    )
    monkeypatch.setattr("scripts.prove_lab.record_completion", lambda *_: None)
    outputs = {}
    for name, stream in (("tty", Terminal()), ("pipe", io.StringIO())):
        monkeypatch.setattr(sys, "stdout", stream)
        shutil_checkout = checkout.parent / name
        for relative_path in {definition[0] for definition in LABS.values()}:
            destination = shutil_checkout / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy2(REPO / relative_path, destination)
        _advance(1, shutil_checkout)
        outputs[name] = stream.getvalue().replace(f"/{name}/", "/run/")

    assert f"\033[{GREEN}mPASS\033[0m: check" in outputs["tty"]
    assert "\033" not in outputs["pipe"]
    assert (
        outputs["tty"].replace(f"\033[{GREEN}m", "").replace("\033[0m", "")
        == outputs["pipe"]
    )


def test_start_ends_with_the_first_step_of_the_lab_it_prepared() -> None:
    @tidy
    def step() -> None:
        lab_state.lab_ready_step(3)

    buffer = io.StringIO()
    saved, sys.stdout = sys.stdout, buffer
    try:
        step()
    finally:
        sys.stdout = saved

    last = assert_ends_with_next(buffer.getvalue(), LIST_TOOLS)
    assert "agent.py" in last


def test_finish_and_skip_to_leave_the_next_step_to_themselves(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("MOSAIC_RUN_BY", "Finish Lab 1")

    lab_state.lab_ready_step(2)

    assert capsys.readouterr().out == ""


def test_status_colours_its_words_and_names_the_first_unsolved_lab(
    monkeypatch,
) -> None:
    lines = {1: "Lab 1: SOLVED", 2: "Lab 2: BROKEN", 3: "Lab 3: NOT STARTED"}
    monkeypatch.setattr(lab_state, "status_line", lambda lab: lines[lab])
    monkeypatch.setattr("sys.argv", ["lab_state.py", "status"])
    outputs = {}
    for name, stream in (("tty", Terminal()), ("pipe", io.StringIO())):
        monkeypatch.setattr(sys, "stdout", stream)
        assert lab_state.main() == 0
        outputs[name] = stream.getvalue().replace(f"/{name}/", "/run/")

    assert f"\033[{GREEN}mSOLVED\033[0m" in outputs["tty"]
    assert f"\033[{RED}mBROKEN\033[0m" in outputs["tty"]
    assert "\033" not in outputs["pipe"]
    paragraphs = assert_well_laid_out(outputs["pipe"])
    assert paragraphs[0] == "\n".join(lines.values())
    assert paragraphs[-1].startswith("Next: fix the marked block in Lab 2's file")


def test_status_when_nothing_has_started_points_at_the_first_start(
    monkeypatch, capsys
) -> None:
    lines = {1: "Lab 1: BROKEN", 2: "Lab 2: NOT STARTED", 3: "Lab 3: NOT STARTED"}
    monkeypatch.setattr(lab_state, "status_line", lambda lab: lines[lab])
    monkeypatch.setattr("sys.argv", ["lab_state.py", "status"])

    lab_state.main()

    last = assert_ends_with_next(capsys.readouterr().out)
    assert "Lab 1" in last


def test_status_when_every_lab_is_solved_points_at_the_wrap_up(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(lab_state, "status_line", lambda lab: f"Lab {lab}: SOLVED")
    monkeypatch.setattr("sys.argv", ["lab_state.py", "status"])

    lab_state.main()

    assert_ends_with_next(capsys.readouterr().out, "Wrap-up")


@pytest.mark.parametrize(
    ("line", "command"),
    [
        ("Lab 2: NOT STARTED", ADVANCE_TO_LAB_2),
        ("Lab 3: REPAIRED, NOT DEPLOYED. Next: deploy.", DEPLOY_AGENT),
    ],
)
def test_status_names_the_command_for_the_first_unsolved_lab(
    monkeypatch, capsys, line, command
) -> None:
    lab = int(line[4])
    solved = {number: f"Lab {number}: SOLVED" for number in (1, 2, 3)}
    monkeypatch.setattr(
        lab_state, "status_line", lambda n: line if n == lab else solved[n]
    )
    monkeypatch.setattr("sys.argv", ["lab_state.py", "status"])

    lab_state.main()

    assert_ends_with_next(capsys.readouterr().out, command)


# ---------------------------------------------------------------- the lab 2 grade


def _lab_2_report(*, wrong: bool) -> dict:
    trial = {
        "contribution_correct": not wrong,
        "target_position": 21,
        "within_cutoff": True,
    }
    return {
        "arms": {"fts": 50, "fuzzy": 0, "semantic": 150},
        "cutoff": 50,
        "k_trials": [{"k": 60, **trial}, {"k": 10, **trial}],
        "saved_run": {
            "rows": 12,
            "distinct_saved_scores": 12,
            "rows_disagreeing_with_correct_fusion": 0,
            "target_saved": True,
        },
        "failures": ["contribution is wrong at k=60; fix it"] if wrong else [],
    }


def _grade(monkeypatch, tmp_path, lab, report, stream) -> tuple[int, str]:
    from scripts import lab_exercise

    work = tmp_path / "work.sql"
    work.write_text("SELECT 1")
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)
    monkeypatch.setattr(lab_exercise, "grade", lambda *_: report)
    monkeypatch.setattr(sys, "stdout", stream)
    code = lab_exercise.main(["grade", "--lab", str(lab), "--work", str(work)])
    return code, stream.getvalue()


def test_the_lab_2_grade_separates_the_k_lines_the_saved_run_and_the_verdict(
    monkeypatch, tmp_path
) -> None:
    code, out = _grade(
        monkeypatch, tmp_path, 2, _lab_2_report(wrong=False), io.StringIO()
    )

    paragraphs = assert_well_laid_out(out)
    assert code == 0
    assert paragraphs[0].startswith("search sizes: ")
    assert paragraphs[0].count("contribution correct") == 2
    assert paragraphs[1].startswith("saved run: 12 rows")
    assert paragraphs[2].startswith("Lab 2 exercise: PASS (")
    assert paragraphs[3].startswith("Next: ")


def test_the_lab_2_grade_ends_with_the_reranking_comparison_the_guide_gives_next(
    monkeypatch, tmp_path
) -> None:
    from service.participant_commands import RERANK_OFF_ON

    _, out = _grade(monkeypatch, tmp_path, 2, _lab_2_report(wrong=False), io.StringIO())

    assert_ends_with_next(out, RERANK_OFF_ON)


def test_a_failed_lab_2_grade_ends_with_the_way_back_not_the_happy_path(
    monkeypatch, tmp_path
) -> None:
    from service.participant_commands import (
        APPLY_SQL,
        RERANK_OFF_ON,
        grade_exercise_command,
    )

    code, out = _grade(
        monkeypatch, tmp_path, 2, _lab_2_report(wrong=True), io.StringIO()
    )

    last = assert_ends_with_next(out, APPLY_SQL, grade_exercise_command(2))
    assert code == 1 and RERANK_OFF_ON not in last
    assert "Lab 2 exercise: FAIL" in out


def test_the_lab_2_grade_colours_each_k_line_and_the_verdict_on_a_terminal(
    monkeypatch, tmp_path
) -> None:
    _, tty = _grade(monkeypatch, tmp_path, 2, _lab_2_report(wrong=True), Terminal())
    _, pipe = _grade(monkeypatch, tmp_path, 2, _lab_2_report(wrong=True), io.StringIO())

    assert f"\033[{RED}mcontribution WRONG\033[0m" in tty
    assert f"\033[{RED}mFAIL\033[0m" in tty
    assert "\033" not in pipe and "contribution WRONG" in pipe
    _, passing = _grade(
        monkeypatch, tmp_path, 2, _lab_2_report(wrong=False), Terminal()
    )
    assert passing.count(f"\033[{GREEN}mcontribution correct\033[0m") == 2


def test_the_lab_3_grade_prints_its_verdict_before_the_wrap_up_step(
    monkeypatch, tmp_path
) -> None:
    _, out = _grade(monkeypatch, tmp_path, 3, {"failures": []}, io.StringIO())

    paragraphs = assert_well_laid_out(out)
    assert paragraphs[0].startswith("Your Retrieval agent is live")
    assert paragraphs[1].startswith("Lab 3 exercise: PASS")
    assert paragraphs[2].startswith("Next: the guide's Wrap-up")


def test_a_failed_lab_3_grade_asks_for_a_new_run_instead_of_the_wrap_up(
    monkeypatch, tmp_path
) -> None:
    from service.participant_commands import grade_setup_run_command

    _, out = _grade(
        monkeypatch,
        tmp_path,
        3,
        {"failures": ["the answer cites nothing"]},
        io.StringIO(),
    )

    last = assert_ends_with_next(out, grade_setup_run_command(), DEPLOY_AGENT)
    assert "Wrap-up" not in last


def test_compare_ends_with_the_lab_3_hand_off(monkeypatch, capsys) -> None:
    from scripts import lab_exercise

    monkeypatch.setattr(lab_exercise, "compare", lambda _lab: {})
    monkeypatch.setattr(lab_exercise, "print_comparison", lambda _table: print("table"))

    assert lab_exercise.main(["compare", "--lab", "2"]) == 0

    assert_ends_with_next(
        capsys.readouterr().out,
        "uv run python scripts/lab_state.py advance --lab 2",
    )


def test_a_comparison_that_cannot_be_measured_ends_with_measuring_again(
    monkeypatch, capsys
) -> None:
    from scripts import lab_exercise
    from service.participant_commands import COMPARE_SETTINGS

    def refuse(_lab):
        raise lab_exercise.ExerciseError("the context is missing")

    monkeypatch.setattr(lab_exercise, "compare", refuse)

    assert lab_exercise.main(["compare", "--lab", "2"]) == 2

    out = capsys.readouterr().out
    assert "CANNOT MEASURE" in out
    assert_ends_with_next(out, COMPARE_SETTINGS)


# ---------------------------------------------------------------- proof, apply, diff, rerank


@pytest.fixture
def proof(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """`prove_lab.py` with its repository, its API checks and Aurora's applied SQL substituted."""
    from scripts import prove_lab

    monkeypatch.setattr(prove_lab, "REPO", tmp_path)
    monkeypatch.setattr(prove_lab, "applied_sql_problem", lambda _lab: None)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)

    def run(lab: int, checker) -> int:
        monkeypatch.setattr(prove_lab, f"prove_lab_{lab}", checker)
        monkeypatch.setattr("sys.argv", ["prove_lab.py", "--lab", str(lab)])
        return prove_lab.main()

    return run


def test_a_passing_lab_1_proof_ends_with_the_hand_off(proof, capsys) -> None:
    proof(1, lambda _url, events: ["Alex's mistyped ID found"])

    out = capsys.readouterr().out
    paragraphs = assert_well_laid_out(out)
    assert paragraphs[0] == "PASS: Alex's mistyped ID found"
    assert paragraphs[1] == "Lab 1: production-path validation passed"
    assert_ends_with_next(out, ADVANCE_TO_LAB_2)


def test_a_failing_proof_ends_with_the_proof_again_not_the_hand_off(
    proof, capsys
) -> None:
    from scripts.prove_lab import LabValidationError
    from service.participant_commands import prove_lab_command

    def failing(_url, events):
        raise LabValidationError("the Logitech is still missing")

    with pytest.raises(SystemExit) as stopped:
        proof(1, failing)

    message = str(stopped.value)
    assert message.splitlines()[-3:] == [
        "",
        "Next: do what the message above says, then run",
        prove_lab_command(1),
    ]


def test_the_proof_colours_pass_on_a_terminal_only(proof, monkeypatch) -> None:
    outputs = {}
    for name, stream in (("tty", Terminal()), ("pipe", io.StringIO())):
        monkeypatch.setattr(sys, "stdout", stream)
        proof(1, lambda _url, events: ["check"])
        outputs[name] = stream.getvalue()

    assert f"\033[{GREEN}mPASS\033[0m: check" in outputs["tty"]
    assert "\033" not in outputs["pipe"]


def test_rerank_off_on_ends_with_the_comparison_of_settings(
    monkeypatch, capsys
) -> None:
    import importlib.util

    from service.participant_commands import COMPARE_SETTINGS

    script = REPO / "labs" / "lab2_rank" / "rerank_off_on.py"
    spec = importlib.util.spec_from_file_location("rerank_layout", script)
    off_on = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(off_on)
    page = {
        "results": [{"product_id": 1, "title": "Dell"}],
        "diagnostics": {
            "rerank_status": "applied",
            "total_latency_ms": 5,
            "stage_timings_ms": {},
        },
    }
    monkeypatch.setattr(off_on, "_request", lambda *_a, **_k: page)

    assert off_on.main([]) == 0

    out = capsys.readouterr().out
    paragraphs = assert_well_laid_out(out)
    assert paragraphs[1].startswith(" #")
    assert_ends_with_next(out, COMPARE_SETTINGS)


@pytest.fixture
def apply_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """`apply_search_functions.py` with Aurora's connection and the settings check replaced."""
    import psycopg

    from scripts import apply_search_functions

    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr("scripts.lab_entry.load_record", lambda *_a, **_k: None)
    monkeypatch.setattr(
        apply_search_functions, "assert_workshop_database", lambda _d: None
    )
    monkeypatch.setattr(apply_search_functions, "missing_file_problem", lambda *_: None)
    monkeypatch.setattr(apply_search_functions, "apply", lambda *_a, **_k: None)
    monkeypatch.setattr(
        apply_search_functions, "fault_untouched", lambda *_a, **_k: False
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: io.StringIO())
    monkeypatch.setattr(
        "scripts.configure_retrieval_database.configure",
        lambda _dsn: print("Aurora retrieval settings verified: {}"),
    )
    return apply_search_functions


def test_apply_separates_what_was_applied_from_the_verified_settings(
    apply_command, capsys
) -> None:
    apply_command.main()

    paragraphs = assert_well_laid_out(capsys.readouterr().out)
    assert paragraphs[0].startswith("Applied participant SQL to ")
    assert paragraphs[1].startswith("Aurora retrieval settings verified")
    assert paragraphs[2].startswith("Next: in psql, run the guide's count query again")


def test_apply_ends_with_the_repeated_request_for_lab_1(apply_command, capsys) -> None:
    apply_command.main()

    assert_ends_with_next(
        capsys.readouterr().out,
        open_psql_command(1),
        "\\q",
        repeat_request_command(1),
    )


def test_apply_ends_with_the_request_and_the_grade_once_lab_2_has_started(
    apply_command, monkeypatch, capsys
) -> None:
    from service.participant_commands import grade_exercise_command

    monkeypatch.setattr(
        "scripts.lab_entry.load_record",
        lambda lab, *_a, **_k: {"completed_at": "2026-11-09T10:00:00+00:00"},
    )

    apply_command.main()

    assert_ends_with_next(
        capsys.readouterr().out,
        open_psql_command(2),
        repeat_request_command(2),
        grade_exercise_command(2),
    )


def test_apply_colours_its_first_line_green_on_a_terminal_only(
    apply_command, monkeypatch
) -> None:
    outputs = {}
    for name, stream in (("tty", Terminal()), ("pipe", io.StringIO())):
        monkeypatch.setattr(sys, "stdout", stream)
        apply_command.main()
        outputs[name] = stream.getvalue()

    assert f"\033[{GREEN}mApplied participant SQL to " in outputs["tty"]
    assert "\033" not in outputs["pipe"]


def test_a_rejected_apply_ends_with_the_fix_as_its_next_step(
    apply_command, monkeypatch
) -> None:
    import psycopg

    from service.participant_commands import APPLY_SQL

    class Rejected(psycopg.errors.SyntaxError):
        @property
        def diag(self):
            return type(
                "Diag",
                (),
                {
                    "sqlstate": "42601",
                    "message_primary": "syntax error",
                    "statement_position": None,
                    "message_hint": None,
                },
            )()

    def fail(*_args, **_kwargs):
        raise Rejected("syntax error")

    monkeypatch.setattr(apply_command, "apply", fail)

    with pytest.raises(SystemExit) as stopped:
        apply_command.main()

    message = str(stopped.value)
    assert "\n\nNext: " in message
    assert message.rstrip().splitlines()[-1] != ""
    assert APPLY_SQL in message.split("\n\nNext: ")[-1]
    assert message.count("Next: ") == 1


def test_diff_points_a_participant_whose_files_match_at_status(
    monkeypatch, capsys
) -> None:
    from scripts import diff
    from service.participant_commands import STATUS

    monkeypatch.setattr("sys.argv", ["diff.py"])
    monkeypatch.setattr(diff, "lab_diff", lambda lab, **_k: ("", False))

    assert diff.main() == 0

    out = capsys.readouterr().out
    assert out.startswith("Every lab file matches the reference answer")
    assert_ends_with_next(out, STATUS)


@pytest.mark.parametrize(
    ("lab", "command"),
    [(1, "apply_search_functions.py"), (3, "deploy_agentcore.py deploy")],
)
def test_diff_ends_with_what_to_do_with_the_lines_it_named(
    monkeypatch, capsys, lab, command
) -> None:
    from scripts import diff

    monkeypatch.setattr("sys.argv", ["diff.py"])
    monkeypatch.setattr(
        diff,
        "lab_diff",
        lambda number, **_k: (f"At line 5 of lab {number}", number == lab),
    )

    diff.main()

    out = capsys.readouterr().out
    paragraphs = assert_well_laid_out(out)
    assert paragraphs[0] == f"At line 5 of lab {lab}"
    assert_ends_with_next(out, command)
