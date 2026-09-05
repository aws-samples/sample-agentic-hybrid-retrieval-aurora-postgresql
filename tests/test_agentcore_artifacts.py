"""Keep the optional AgentCore Runtime artifacts honest.

Nothing under `deploy/agentcore/` is on the required lab path and nothing here
deploys anything. These checks guard the claims those artifacts make: the image
resolves from the committed lock, it never carries a credential file and never
runs as root, it ships the module its command runs, and
`docs/agentcore-runtime.md` names every deployment environment variable the
service actually reads. The variable list is derived
from `config/.env.example` rather than restated here, so adding a setting to
the example file reds this gate until the runtime document explains it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "deploy" / "agentcore" / "Dockerfile"
ADAPTER = ROOT / "deploy" / "agentcore" / "app.py"
RUNTIME_DOC = ROOT / "docs" / "agentcore-runtime.md"
ENV_EXAMPLE = ROOT / "config" / ".env.example"
MAKEFILE = ROOT / "Makefile"

AGENTCORE_TARGETS = ("agentcore-image", "agentcore-image-smoke", "agentcore-deploy")

#: The container entry point. It is the adapter rather than `service.main:app`
#: because the two contract routes live there; behavior of the adapter itself is
#: `tests/test_agentcore_adapter.py`.
ADAPTER_MODULE = "deploy.agentcore.app:app"

#: A floor, not the expected count. `config/.env.example` carried fifteen
#: uncommented assignments when this gate was written. The floor exists so a
#: regex that stops matching fails loudly instead of asserting over an empty
#: set, which is the fail-open shape house standards rule 7 rejects.
MINIMUM_DEPLOYMENT_SETTINGS = 10


def _instructions(dockerfile: str) -> list[str]:
    """Every Dockerfile instruction, continuations joined, comments dropped."""
    joined = re.sub(r"\\\s*\n", " ", dockerfile)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _copy_sources(dockerfile: str) -> list[str]:
    """Source paths of every COPY, ignoring flags and the destination."""
    sources: list[str] = []
    for line in _instructions(dockerfile):
        if not line.upper().startswith("COPY "):
            continue
        arguments = [token for token in line.split()[1:] if not token.startswith("--")]
        sources.extend(arguments[:-1])
    return sources


def _deployment_settings() -> list[str]:
    """Names the example file assigns a value to.

    `config/.env.example` states its own split: retrieval numbers live in
    `db/config/retrieval.yaml` and are deliberately listed without values, so
    every name that still carries an assignment in the example file is a
    deployment or service setting the runtime has to be given.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE)))


def _makefile_rules() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Za-z0-9_.-]+):(?!=)", text, flags=re.MULTILINE))


def test_dockerfile_resolves_dependencies_from_the_committed_lock():
    assert DOCKERFILE.is_file(), f"missing {DOCKERFILE.relative_to(ROOT)}"
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "uv sync --frozen" in dockerfile, (
        "found no `uv sync --frozen`; fix: resolve from uv.lock so the image "
        "installs the same dependency set the repository pins"
    )
    assert "uv.lock" in _copy_sources(dockerfile), (
        "found no COPY of uv.lock; fix: copy pyproject.toml and uv.lock before "
        "the sync step so `--frozen` has a lock to read"
    )


def test_dockerfile_never_copies_a_credential_file():
    """`.env` holds a live Aurora DSN. It must not enter an image layer."""
    sources = _copy_sources(DOCKERFILE.read_text(encoding="utf-8"))

    for source in sources:
        assert source not in {".", "./"}, (
            f"found `COPY {source}`; fix: copy explicit paths, because the build "
            "context root holds a real .env on a facilitator machine"
        )
        assert "*" not in source, (
            f"found a wildcard COPY source `{source}`; fix: name the paths, so a "
            "glob cannot sweep a credential file into the image"
        )
        assert not source.endswith(".env"), f"found `COPY {source}` of a dotenv file"


def test_dockerfile_runs_as_a_non_root_user():
    users = [
        line.split()[1]
        for line in _instructions(DOCKERFILE.read_text(encoding="utf-8"))
        if line.upper().startswith("USER ")
    ]

    assert users, (
        "found no USER instruction; fix: add one, AgentCore runs the image as given"
    )
    assert users[-1] not in {"root", "0", "0:0"}, (
        f"found final `USER {users[-1]}`; fix: switch to an unprivileged user"
    )


def test_dockerfile_binds_the_agentcore_http_contract():
    """HTTP protocol: ARM64, port 8080, bound to 0.0.0.0 for internal routing."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    instructions = _instructions(dockerfile)

    assert any(line.upper().startswith("EXPOSE 8080") for line in instructions)
    assert "linux/arm64" in dockerfile, (
        "found no linux/arm64 platform; fix: AgentCore Runtime is Graviton and "
        "an x86 image will not start"
    )
    command = next(line for line in instructions if line.upper().startswith("CMD "))
    assert ADAPTER_MODULE in command, (
        f"found a CMD that does not run {ADAPTER_MODULE}; fix: the adapter is "
        "what serves GET /ping and POST /invocations, and running the workshop "
        "application directly fails the AgentCore health check"
    )
    assert "0.0.0.0" in command
    assert "8080" in command


def test_dockerfile_ships_the_module_its_command_runs():
    """A CMD naming a file no COPY carries starts into an ImportError."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entry_point = ADAPTER_MODULE.split(":")[0].replace(".", "/") + ".py"

    assert ADAPTER.is_file(), f"missing {ADAPTER.relative_to(ROOT)}"
    assert entry_point in _copy_sources(dockerfile), (
        f"found no COPY of {entry_point}; fix: copy the entry point, because "
        "the image otherwise has no module for its CMD to import"
    )


def test_makefile_declares_the_agentcore_targets():
    rules = _makefile_rules()
    missing = [target for target in AGENTCORE_TARGETS if target not in rules]

    assert not missing, f"found no Makefile rule for {missing}"


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_plans_the_image_build_without_running_it():
    completed = subprocess.run(
        ["make", "-n", "agentcore-image"],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "DATABASE_URL": ""},
    )

    assert completed.returncode == 0, completed.stderr
    assert "deploy/agentcore/Dockerfile" in completed.stdout


def test_runtime_document_names_every_deployment_setting():
    assert RUNTIME_DOC.is_file(), f"missing {RUNTIME_DOC.relative_to(ROOT)}"
    settings = _deployment_settings()

    assert (
        "DATABASE_URL" in settings and len(settings) >= MINIMUM_DEPLOYMENT_SETTINGS
    ), (
        f"found {len(settings)} settings in config/.env.example; fix: the "
        "derivation broke, so this gate was about to pass over an empty set"
    )

    document = RUNTIME_DOC.read_text(encoding="utf-8")
    undocumented = [name for name in settings if name not in document]

    assert not undocumented, (
        f"found undocumented deployment settings {undocumented}; fix: name each "
        "one in docs/agentcore-runtime.md and say where the runtime gets it"
    )
