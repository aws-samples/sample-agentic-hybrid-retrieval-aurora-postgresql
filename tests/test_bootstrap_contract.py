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


def test_bootstrap_installs_one_node_family_and_asserts_it(script: str) -> None:
    """AL2023 arbitrates Node through `alternatives`, so asking for two loses.

    The bare `npm` package is Node 18's and pulls nodejs-18 in as a dependency. A
    box that asked for `nodejs20 npm` ran Node 18: npm reported EBADENGINE for
    @anthropic-ai/claude-code, which declares `node >=22`, and the tool ran outside
    its supported engine. Requesting exactly one family removes the arbitration,
    and asserting the active version turns a wrong link into an immediate failure
    rather than a Claude Code preflight that times out three times.
    """
    packages = _bootstrap_packages(script)
    node_packages = {name for name in packages if name.startswith("nodejs")}
    assert node_packages == {"nodejs22", "nodejs22-npm"}, (
        f"the bootstrap requests Node packages {sorted(node_packages)}; ask for one "
        "family only, and for 22 because the pinned Claude Code needs node >=22"
    )
    assert "npm" not in packages, (
        "the unversioned npm package is Node 18's and installs nodejs-18 as a "
        "dependency, which then wins the alternatives link"
    )
    assert r"node --version | grep -Eq '^v22\.'" in script, (
        "the bootstrap does not assert which Node is active, so a wrong "
        "alternatives link surfaces later as an EBADENGINE warning"
    )


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


def test_bootstrap_blocks_commits_without_breaking_diff(script: str) -> None:
    """The checkout must refuse commits while still reading as a working tree.

    A committed lab edit empties the diff a participant is asked to inspect, and
    it leaves a checkout whose history no longer matches the pinned revision.
    Reading stays intact because the bootstrap asserts the Lab 1 seam with
    `git diff --name-only` and the API records `source_worktree_dirty`.
    """
    assert "core.hooksPath /opt/mosaic-workshop/git-hooks" in script, (
        "point core.hooksPath at a hook directory outside the checkout"
    )
    assert "/opt/mosaic-workshop/git-hooks/pre-commit" in script, (
        "install a pre-commit hook that refuses commits"
    )
    assert "Commits are disabled in this workshop checkout." in script, (
        "the refusal must explain itself to a participant"
    )
    assert ".githooks" not in script, (
        "a hook directory inside the checkout shows up as untracked in git status"
    )
    assert 'git -C "$REPO" diff --name-only' in script, (
        "the Lab 1 seam assertion still depends on reading the diff"
    )


def test_bare_psql_reaches_aurora_from_any_shell(script: str) -> None:
    """`psql` with no arguments and "$DATABASE_URL" must both work in a new shell.

    Twenty-seven lab commands use "$DATABASE_URL". The guide sourced .env once on
    the introduction page, so a second terminal ran them as psql "" and fell back
    to a Unix socket that does not exist on this host.
    """
    assert "[ -r '$REPO/.env' ] && . '$REPO/.env'" in script, (
        "every interactive shell must load the generated .env"
    )
    for variable in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGSSLMODE"):
        assert f"export {variable}=" in script, (
            f"libpq needs {variable} for a bare psql invocation"
        )
    assert "/.pgpass" in script, (
        "the password belongs in ~/.pgpass, not the environment"
    )
    assert 'chmod 600 "/home/$CODE_EDITOR_USER/.pgpass"' in script, (
        "libpq refuses a ~/.pgpass that is not 0600"
    )
    assert "psql -X -Atc 'SELECT 1'" in script, (
        "prove the participant connection during bootstrap, not at the lab"
    )


def test_code_editor_hides_git_and_is_legible(script: str) -> None:
    """No source-control decorations, and readable at the back of a room."""
    assert '"git.enabled": false' in script, (
        "the injected Lab 1 seam showed as a modified badge a participant may revert"
    )
    assert '"workbench.colorTheme": "Default Dark Modern"' in script
    assert '"terminal.integrated.fontSize": 18' in script
    assert '"window.zoomLevel"' in script, "whole-UI scale, not just the editor font"


def test_claude_code_skips_its_first_run_prompt(script: str) -> None:
    """Onboarding is version-gated, so the flag alone is not enough."""
    assert '"hasCompletedOnboarding"' in script, "the flag itself"
    assert '"lastOnboardingVersion"' in script, (
        "onboarding re-runs when the recorded version predates the installed CLI"
    )
    assert "$CLAUDE_CODE_VERSION" in script, (
        "the install and the onboarding version must come from one pin"
    )


def test_bootstrap_never_executes_a_file_it_does_not_create(script: str) -> None:
    """Every interpreter target must exist on the box by the time it runs.

    A previous revision called python3.13 on a helper under /opt that nothing ever
    copied there, and the contract test asserted only that the *filename* appeared
    in the script, so it passed while the path was unreachable. Assert the path is
    real instead of asserting a string is present.
    """
    invocations = re.findall(
        r"(?:python3\.13|python3|bash|sh)\s+((?:/|\$)[^\s\\'\"]+)", script
    )
    unreachable = []
    for target in set(invocations):
        if target.startswith("$REPO"):
            continue  # the checkout, verified against SOURCE_REVISION earlier
        created = (
            f'cat >"{target}"' in script
            or f"cat >{target}" in script
            or f"install -d {target}" in script
            or f'-o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" {target}' in script
        )
        if not created:
            unreachable.append(target)
    assert not unreachable, (
        f"bootstrap executes paths it never creates: {sorted(unreachable)}; "
        "inline the code or install the file before calling it"
    )


def test_code_editor_opens_a_terminal_and_skips_the_trust_prompt(script: str) -> None:
    """First open should land in a terminal with no dialogs in the way.

    A folderOpen task only fires from the .vscode of the folder Code Editor
    actually opens, which is `$REPO` per --default-folder, not its parent. And
    without task.allowAutomaticTasks the editor prompts instead of running it, so
    both halves have to be present for the terminal to appear by itself.
    """
    assert '"runOn": { "runOn"' not in script, "runOptions is the wrapping key"
    assert '"runOn": "folderOpen"' in script, "the task must run on folder open"
    assert '"$REPO/.vscode"' in script, (
        "write the task into the opened folder, not the parent"
    )
    assert '"task.allowAutomaticTasks": "on"' in script, (
        "without this Code Editor prompts rather than running the task"
    )
    for key in (
        '"security.workspace.trust.enabled": false',
        '"security.workspace.trust.startupPrompt": "never"',
    ):
        assert key in script, f"missing workspace-trust suppression: {key}"
    assert ".code-editor-server/data/User" in script, (
        "user settings belong in the server's own user-data directory"
    )
