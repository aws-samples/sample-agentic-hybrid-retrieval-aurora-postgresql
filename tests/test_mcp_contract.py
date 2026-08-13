from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_2026_runtime_is_isolated_from_strands() -> None:
    pyproject = tomllib.loads(
        (ROOT / "mcp-server" / "pyproject.toml").read_text()
    )
    mcp_dependencies = pyproject["project"]["dependencies"]
    shared_dependencies = (
        ROOT / "config" / "requirements.txt"
    ).read_text().splitlines()

    assert "mcp==2.0.0" in mcp_dependencies
    assert pyproject["project"]["requires-python"] == ">=3.13,<3.14"
    assert not any(line.startswith("mcp") for line in shared_dependencies)
    assert "strands-agents==1.48.0" in shared_dependencies


def test_mosaic_runtime_contract_is_python_313() -> None:
    makefile = (ROOT / "Makefile").read_text()

    assert (ROOT / ".python-version").read_text().strip() == "3.13.14"
    assert "PYTHON_VERSION := 3.13" in makefile
    assert "Mosaic requires Python 3.13" in makefile


def test_mcp_server_uses_stateless_2026_transport_and_api_contracts() -> None:
    source = (
        ROOT / "mcp-server" / "catalog_mcp" / "server.py"
    ).read_text()

    assert "stateless_http=True" in source
    assert 'name="mosaic-retrieval"' in source
    assert "SearchResponse.model_validate(payload)" in source
    assert "ProductEvidenceResponse.model_validate(payload)" in source
    assert "RetrievalRunResponse.model_validate(payload)" in source
    assert "from service.models import" in source
    assert "us.cohere.embed-v4:0" not in source
