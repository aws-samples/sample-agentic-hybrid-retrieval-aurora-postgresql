"""The Code Editor bootstrap has to agree with the application it boots.

`deploy/mosaic-bootstrap.sh` encodes ports, routes, module paths and Make targets
that this repository owns. Nothing used to connect the two, so renaming a route or
moving a port broke the box silently and a participant found out as a CloudFormation
wait-condition timeout. That is the most expensive place to learn it.

Every expectation below is read from the authoritative source rather than restated
here. A test that carried its own copy of the port could not catch a port change:
it would simply agree with itself. See docs in `deploy/README.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from service.main import app

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "deploy" / "mosaic-bootstrap.sh"
MAKEFILE = ROOT / "Makefile"
VITE_CONFIG = ROOT / "ui" / "vite.config.ts"


@pytest.fixture(scope="module")
def script() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


def _make_default(name: str) -> str:
    """The value the Makefile assigns, which is what the workshop is built on."""
    # This Makefile uses all three assignment forms: `:=`, `?=` and `=`.
    match = re.search(
        rf"^{re.escape(name)}\s*[:?]?=\s*(\S+)",
        MAKEFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"{name} is no longer assigned in the Makefile"
    return match.group(1)


def test_the_source_of_truth_is_here(script: str) -> None:
    assert BOOTSTRAP.exists()
    # A bootstrap that does not start the two units is not this bootstrap.
    assert "mosaic-api" in script
    assert "mosaic-ui" in script


def test_api_unit_serves_the_makefile_api_port(script: str) -> None:
    port = _make_default("API_PORT")
    assert f"--port {port}" in script, (
        f"the API unit does not serve API_PORT={port}; a participant would get a "
        "box whose API is on a port nothing else expects"
    )
    assert f"http://127.0.0.1:{port}" in script


def test_ui_unit_serves_the_makefile_ui_port(script: str) -> None:
    port = _make_default("UI_PORT")
    assert f"--port {port}" in script


def test_api_unit_runs_the_asgi_app_this_repository_exposes(script: str) -> None:
    # The import path uvicorn is given has to be the one that actually imports.
    assert "service.main:app" in script
    assert app is not None


def test_health_probes_are_routes_the_app_registers(script: str) -> None:
    probed = set(re.findall(r"127\.0\.0\.1:\d+(/api/[a-z/_-]+)", script))
    assert probed, "the bootstrap no longer probes the API before signalling success"

    registered = {getattr(route, "path", None) for route in app.routes}
    missing = sorted(path for path in probed if path not in registered)
    assert missing == [], (
        f"the bootstrap waits on {missing}, which the app does not serve, so the "
        "wait condition can only ever time out"
    )


def test_vite_proxy_variable_is_the_one_vite_reads(script: str) -> None:
    config = VITE_CONFIG.read_text(encoding="utf-8")
    names = set(re.findall(r"process\.env\.([A-Z_][A-Z0-9_]*)", config))
    assert names, "vite.config.ts no longer reads a proxy target from the environment"
    for name in names:
        assert f"{name}=" in script, (
            f"vite reads {name} but the bootstrap never sets it, so the UI would "
            "proxy to its built-in default instead of the API on this box"
        )


def test_database_bootstrap_target_exists(script: str) -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    for target in re.findall(r"^\s*make ([a-z][a-z0-9-]*)", script, re.MULTILINE):
        assert re.search(rf"^{re.escape(target)}:", makefile, re.MULTILINE), (
            f"the bootstrap runs `make {target}`, which this Makefile no longer has"
        )


def test_embedding_model_matches_the_application_default(script: str) -> None:
    from service.config import get_settings

    configured = get_settings().embedding_model_id
    assert f"BEDROCK_EMBED_MODEL_ID={configured}" in script, (
        f"the bootstrap pins an embedding model other than {configured}; the box "
        "would embed with one model and serve a corpus built by another"
    )


def test_python_and_venv_match_what_the_makefile_requires(script: str) -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    version = _make_default("PYTHON_VERSION")

    # Every interpreter the script names, not merely one of them. Asserting that
    # `python3.13` appears somewhere passes while half the invocations have moved
    # to another minor, which is exactly how this drifts in practice.
    named = set(re.findall(r"python3\.\d+", script))
    assert named == {f"python{version}"}, (
        f"the Makefile requires Python {version}, and the bootstrap names "
        f"{sorted(named)}; a box built on two minors resolves a different lockfile"
    )
    assert f"expected = ({version.replace('.', ', ')})" in makefile

    venv = _make_default("VENV")
    assert f"/{venv}/bin/" in script, (
        f"the API unit does not run out of {venv}, which is where `make setup` builds"
    )


def test_uv_is_pinned_rather_than_floating(script: str) -> None:
    # Not compared to a repository value: nothing here declares a uv version. The
    # checkable property is that a workshop does not install a moving target.
    assert re.search(r"uv==\d+\.\d+\.\d+", script), (
        "the bootstrap installs uv without a pin, so two participants can get "
        "different resolvers on the same commit"
    )


def _bootstrap_packages(script: str) -> list[str]:
    """Return the AL2023 packages installed before the application bootstrap."""
    package_install = re.search(
        r"^dnf install -y (?P<packages>.*?\bunzip)$",
        script,
        re.MULTILINE | re.DOTALL,
    )
    assert package_install, "the bootstrap package installation could not be found"
    return package_install.group("packages").replace("\\\n", " ").split()


def test_al2023_bootstrap_does_not_request_full_curl(script: str) -> None:
    """Amazon Linux 2023 already provides curl-minimal, which conflicts with curl."""
    packages = _bootstrap_packages(script)
    assert "curl" not in packages, (
        "AL2023 ships curl-minimal; do not request the conflicting full curl RPM"
    )


def test_al2023_bootstrap_uses_the_native_postgresql_client(script: str) -> None:
    """RHEL PGDG RPMs require a libldap ABI that AL2023 does not ship."""
    assert "postgresql15" in _bootstrap_packages(script), (
        "install AL2023's postgresql15 package instead of a RHEL PGDG client RPM"
    )
    assert "PGDG_BASE" not in script, (
        "do not mix RHEL PGDG RPMs into AL2023; they need unavailable libldap.so.2"
    )
    assert "sslnegotiation=direct" not in script, (
        "postgresql15 predates sslnegotiation=direct; use sslmode=require for psql"
    )
    assert "psql --version | grep -Eq '^psql \\(PostgreSQL\\) 15\\.'" in script, (
        "verify the AL2023 PostgreSQL 15 client was installed before using psql"
    )
