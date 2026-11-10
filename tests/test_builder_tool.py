"""The build check must reject broken participant code through the real callable."""

import io
import re
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_synthesis_claims import product

from examples import call_headphones
from scripts.check_builder_tool import BuilderCheckError, check_tool, load_example
from service import main
from service.builder_package import BUILDER_FILES
from service.models import SearchResponse


@pytest.fixture
def network(monkeypatch):
    posts = []
    reads = []
    receipts = {}

    def post(url, *, json, timeout, headers=None):
        posts.append(json)
        run_id = f"00000000-0000-4000-8000-{len(posts):012d}"
        response = SearchResponse(
            search_event_id=run_id,
            query=json["query"],
            normalized_query=json["query"],
            applied_filters=json["filters"],
            results=[
                product(
                    domain="consumer_electronics",
                    category_key="headphones",
                    brand=json["filters"].get("brand"),
                    price_cents=None,
                )
            ],
            diagnostics=None,
        ).model_dump(mode="json")
        receipts[run_id] = response
        return httpx.Response(200, json=response, request=httpx.Request("POST", url))

    def get(url, *, timeout, headers=None):
        reads.append(url)
        response = receipts[url.split("/events/")[1].split("/")[0]]
        return httpx.Response(200, json=response, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    return posts, reads, receipts


def test_working_tool_uses_each_brand_and_replays_both_saved_searches(network):
    posts, reads, _ = network
    result = check_tool(call_headphones, ["Bose", "Sony"], "Headphones for calls")
    assert len(posts) == len(reads) == len(result) == 2
    assert [post["filters"]["brand"] for post in posts] == ["Bose", "Sony"]
    assert all(item["products_checked"] == 1 for item in result)
    # A different preference changes neither the enforced rule nor registration.
    check_tool(call_headphones, ["Bose", "Sony"], "Lightweight headphones")
    assert len(posts) == 4


def test_generated_starter_fails_until_both_implementation_points_are_completed(
    tmp_path, network
):
    destination = tmp_path / "participant.py"
    source = Path(call_headphones.__file__).read_bytes()
    call_headphones.write_starter(destination)
    starter = load_example(destination)
    with pytest.raises(BuilderCheckError, match="registered_tools"):
        check_tool(starter, ["Bose", "Sony"], "Calls")
    starter.registered_tools = lambda: [starter.search_call_headphones]
    with pytest.raises(NotImplementedError, match="Build the SearchFilters"):
        check_tool(starter, ["Bose", "Sony"], "Calls")
    starter.call_filters = call_headphones.call_filters
    assert len(check_tool(starter, ["Bose", "Sony"], "Calls")) == 2
    assert Path(call_headphones.__file__).read_bytes() == source
    with pytest.raises(FileExistsError):
        call_headphones.write_starter(destination)


@pytest.mark.parametrize("fault", ["category", "brand"])
def test_missing_filter_and_hardcoded_brand_fail_with_the_wrong_value(
    monkeypatch, network, fault
):
    original = call_headphones.call_filters

    def broken(brand):
        filters = original(brand)
        if fault == "category":
            filters.category_key = None
        else:
            filters.brand = "Bose"
        return filters

    monkeypatch.setattr(call_headphones, "call_filters", broken)
    with pytest.raises(
        BuilderCheckError,
        match="category_key" if fault == "category" else "brand",
    ):
        check_tool(call_headphones, ["Bose", "Sony"], "Headphones")
    assert network[0], "the registered tool must have reached the HTTP boundary"


def test_empty_brand_list_cannot_report_a_vacuous_pass(network):
    with pytest.raises(BuilderCheckError, match="two distinct brands"):
        check_tool(call_headphones, [], "Headphones")
    assert network[0] == []


def test_download_contains_exact_reference_files_and_no_local_state():
    response = TestClient(main.app).get("/api/builder-package")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "mosaic-builder/README.md",
            *(f"mosaic-builder/{path}" for path in BUILDER_FILES),
        }
        assert "examples/call_headphones.py" in BUILDER_FILES
        # The kit is reference material, so it carries each lab's answer
        # rather than whatever state a participant's workspace copy is in.
        assert "labs/lab1_retrieve/solution/hybrid_search.sql" in BUILDER_FILES
        assert "labs/lab1_retrieve/hybrid_search.sql" not in BUILDER_FILES
        for path in BUILDER_FILES:
            assert (
                archive.read(f"mosaic-builder/{path}")
                == (main.ROOT / path).read_bytes()
            )
        assert not any(
            ".env" in name or ".local" in name for name in archive.namelist()
        )


def test_the_kit_carries_every_sql_file_its_documents_name():
    """A guide that maps a concept to a SQL file must ship that file."""
    named = set()
    for path in BUILDER_FILES:
        if path.endswith(".md"):
            named |= set(
                re.findall(r"db/sql/[\w.-]+\.sql", (main.ROOT / path).read_text())
            )
    assert named, "the kit's guides name no SQL file; this gate would be vacuous"
    missing = sorted(named - set(BUILDER_FILES))
    assert not missing, (
        f"Builder kit rule: its guides name {missing}, which the download leaves out; "
        "fix: add them to BUILDER_FILES in service/builder_package.py."
    )


def test_missing_download_files_name_the_restore_action(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    response = TestClient(main.app).get("/api/builder-package")
    assert response.status_code == 503
    assert (
        "restore the files listed in service/builder_package.py"
        in response.json()["detail"]
    )


def test_the_agent_answer_ends_its_line(monkeypatch, capsys):
    """Strands streams the answer without a final newline; the shell prompt must not
    land on its last line."""
    monkeypatch.setattr(
        call_headphones, "create_agent", lambda: lambda _prompt: print("Bose", end="")
    )
    monkeypatch.setattr(
        "sys.argv",
        ["call_headphones", "--agent", "--query", "calls", "--brand", "Bose"],
    )
    call_headphones.main()
    assert capsys.readouterr().out == "Bose\n"


# ---------------------------------------------------------------- progress, JSON and Next


def _run_checker(monkeypatch, argv, *, stdout=None, stderr=None):
    from scripts import check_builder_tool

    monkeypatch.setattr("sys.argv", ["check_builder_tool", *argv])
    if stdout is not None:
        monkeypatch.setattr("sys.stdout", stdout)
    if stderr is not None:
        monkeypatch.setattr("sys.stderr", stderr)
    return check_builder_tool.main()


def test_each_brand_search_is_a_step_with_the_time_waited_and_stdout_stays_json(
    network, monkeypatch, capsys
):
    import json

    _run_checker(monkeypatch, ["--module", str(call_headphones.__file__)])

    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "passed"
    steps = [line for line in captured.err.splitlines() if line.startswith("  - ")]
    assert steps == [
        "  - 1/2  Search Bose headphones and check the saved search",
        "  - 2/2  Search Sony headphones and check the saved search",
    ]
    assert "usually" not in captured.err


def test_the_checker_ends_with_the_agent_step_on_stderr_so_stdout_stays_json(
    network, monkeypatch, capsys
):
    from service.participant_commands import call_headphones_agent_command

    module = str(call_headphones.__file__)
    _run_checker(monkeypatch, ["--module", module])

    captured = capsys.readouterr()
    assert captured.out.rstrip("\n").endswith("}")
    assert "Next" not in captured.out
    assert captured.err.endswith(
        "\n\nNext: let the Retrieval agent call your tool:\n"
        f"{call_headphones_agent_command(module)}\n"
    )


def test_status_passed_is_green_on_a_terminal_and_plain_when_piped(
    network, monkeypatch
):
    import io

    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    module = str(call_headphones.__file__)
    painted, plain = Terminal(), io.StringIO()

    _run_checker(
        monkeypatch, ["--module", module], stdout=painted, stderr=io.StringIO()
    )
    _run_checker(monkeypatch, ["--module", module], stdout=plain, stderr=io.StringIO())

    assert '\033[1;32m"status": "passed"\033[0m' in painted.getvalue()
    assert '"status": "passed"' in plain.getvalue()
    assert "\033" not in plain.getvalue()


def test_a_failing_tool_ends_with_a_next_that_checks_it_again(
    network, monkeypatch, capsys, tmp_path
):
    from service.participant_commands import check_builder_tool_command

    starter = tmp_path / "participant.py"
    call_headphones.write_starter(starter)

    with pytest.raises(SystemExit):
        _run_checker(monkeypatch, ["--module", str(starter)])

    err = capsys.readouterr().err
    assert "\n\nNext: fix what the message above names, then run this again:\n" in err
    assert err.rstrip("\n").endswith(check_builder_tool_command(str(starter)))
    assert err.startswith("Build check failed: ")
