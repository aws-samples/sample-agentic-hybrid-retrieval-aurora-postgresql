"""The build check must reject broken participant code through the real callable."""

import io
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

    def post(url, *, json, timeout):
        posts.append(json)
        run_id = f"00000000-0000-4000-8000-{len(posts):012d}"
        response = SearchResponse(
            search_event_id=run_id,
            query=json["query"],
            normalized_query=json["query"],
            applied_filters=json["filters"],
            results=[
                product(
                    category_key="over-ear-headphones",
                    attributes={"microphone": True},
                    price_cents=5000,
                )
            ],
            diagnostics=None,
        ).model_dump(mode="json")
        receipts[run_id] = response
        return httpx.Response(200, json=response, request=httpx.Request("POST", url))

    def get(url, *, timeout):
        reads.append(url)
        response = receipts[url.split("/events/")[1].split("/")[0]]
        return httpx.Response(200, json=response, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    return posts, reads, receipts


def test_working_tool_uses_each_budget_and_replays_both_saved_searches(network):
    posts, reads, _ = network
    result = check_tool(call_headphones, [20000, 10000], "Headphones for calls")
    assert len(posts) == len(reads) == len(result) == 2
    assert [post["filters"]["max_price_cents"] for post in posts] == [20000, 10000]
    assert all(item["products_checked"] == 1 for item in result)
    # A different preference changes neither the enforced rule nor registration.
    check_tool(call_headphones, [20000, 10000], "Lightweight headphones")
    assert len(posts) == 4


def test_generated_starter_fails_until_both_implementation_points_are_completed(
    tmp_path, network
):
    destination = tmp_path / "participant.py"
    source = Path(call_headphones.__file__).read_bytes()
    call_headphones.write_starter(destination)
    starter = load_example(destination)
    with pytest.raises(BuilderCheckError, match="registered_tools"):
        check_tool(starter, [20000, 10000], "Calls")
    starter.registered_tools = lambda: [starter.search_call_headphones]
    with pytest.raises(NotImplementedError, match="Build the SearchFilters"):
        check_tool(starter, [20000, 10000], "Calls")
    starter.call_filters = call_headphones.call_filters
    assert len(check_tool(starter, [20000, 10000], "Calls")) == 2
    assert Path(call_headphones.__file__).read_bytes() == source
    with pytest.raises(FileExistsError):
        call_headphones.write_starter(destination)


@pytest.mark.parametrize("fault", ["microphone", "budget"])
def test_missing_filter_and_hardcoded_budget_fail_with_the_wrong_value(
    monkeypatch, network, fault
):
    original = call_headphones.call_filters

    def broken(budget):
        filters = original(budget)
        if fault == "microphone":
            filters.attributes = {}
        else:
            filters.max_price_cents = 20000
        return filters

    monkeypatch.setattr(call_headphones, "call_filters", broken)
    with pytest.raises(
        BuilderCheckError,
        match="attributes" if fault == "microphone" else "max_price_cents",
    ):
        check_tool(call_headphones, [20000, 10000], "Headphones")
    assert network[0], "the registered tool must have reached the HTTP boundary"


def test_empty_budget_list_cannot_report_a_vacuous_pass(network):
    with pytest.raises(BuilderCheckError, match="two distinct budgets"):
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
        assert "db/sql/09_search_functions.sql" in BUILDER_FILES
        for path in BUILDER_FILES:
            assert (
                archive.read(f"mosaic-builder/{path}")
                == (main.ROOT / path).read_bytes()
            )
        assert not any(
            ".env" in name or ".local" in name for name in archive.namelist()
        )


def test_missing_download_files_name_the_restore_action(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    response = TestClient(main.app).get("/api/builder-package")
    assert response.status_code == 503
    assert (
        "restore the files listed in service/builder_package.py"
        in response.json()["detail"]
    )
