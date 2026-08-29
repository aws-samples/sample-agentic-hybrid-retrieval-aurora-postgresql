"""Bind release evidence to the source SHA and delivered Studio bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


class ReleaseContractError(ValueError):
    """A release input disagrees with the source being certified."""


def _required_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ReleaseContractError(
            f"{label} is missing at {path}; fix: set MOSAIC_WORKSHOP_REPO to "
            "a complete Workshop Studio checkout"
        )
    return path


def _parameter_default(text: str, parameter: str, label: str) -> str:
    match = re.search(
        rf"templateParameter:\s*{re.escape(parameter)}\s*\n"
        rf"\s*defaultValue:\s*[\"']([^\"']+)[\"']",
        text,
    )
    if not match:
        raise ReleaseContractError(
            f"{label} has no quoted default for {parameter}; "
            "fix: repin the Workshop Studio release metadata"
        )
    return match.group(1)


def _cfn_default(text: str, parameter: str, label: str) -> str:
    match = re.search(
        rf"^\s{{2}}{re.escape(parameter)}:\s*\n"
        rf"(?:^\s{{4,}}.*\n)*?^\s{{4}}Default:\s*([^\s]+)\s*$",
        text,
        re.MULTILINE,
    )
    if not match:
        raise ReleaseContractError(
            f"{label} has no default for {parameter}; "
            "fix: repin the Workshop Studio CloudFormation chain"
        )
    return match.group(1).strip("'\"")


def _git_head(repository: Path, label: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReleaseContractError(
            f"{label} at {repository} is not a Git checkout; "
            "fix: point the release lane at the version-controlled checkout"
        )
    return result.stdout.strip()


def _git_dirty(repository: Path, label: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReleaseContractError(
            f"{label} at {repository} has no readable Git status; "
            "fix: repair or replace the release checkout"
        )
    return bool(result.stdout.strip())


def verify_delivery(
    source_repo: Path,
    workshop_repo: Path,
    expected_source_sha: str,
    *,
    source_head: str | None = None,
    workshop_head: str | None = None,
    workshop_dirty: bool | None = None,
) -> dict[str, Any]:
    """Verify immutable source, Studio pin, bootstrap bytes, and hash consumers."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_sha):
        raise ReleaseContractError(
            f"release source SHA is {expected_source_sha!r}; "
            "fix: pass the full 40-character GitHub commit SHA"
        )

    actual_source_sha = source_head or _git_head(source_repo, "source repository")
    if actual_source_sha != expected_source_sha:
        raise ReleaseContractError(
            f"checked-out source is {actual_source_sha}, but release evidence "
            f"claims {expected_source_sha}; fix: check out the tagged SHA"
        )

    source_bootstrap = _required_file(
        source_repo / "deploy" / "mosaic-bootstrap.sh",
        "source bootstrap",
    )
    delivered_bootstrap = _required_file(
        workshop_repo / "assets" / "mosaic-bootstrap.sh",
        "delivered bootstrap",
    )
    contentspec_path = _required_file(
        workshop_repo / "contentspec.yaml",
        "Workshop Studio contentspec",
    )
    main_template_path = _required_file(
        workshop_repo / "static" / "hybrid-retrieval-main.yml",
        "Workshop Studio main template",
    )
    editor_template_path = _required_file(
        workshop_repo / "assets" / "hybrid-retrieval-code-editor.yml",
        "Workshop Studio Code Editor template",
    )

    source_bytes = source_bootstrap.read_bytes()
    delivered_bytes = delivered_bootstrap.read_bytes()
    if source_bytes != delivered_bytes:
        raise ReleaseContractError(
            "delivered assets/mosaic-bootstrap.sh differs from "
            "deploy/mosaic-bootstrap.sh; fix: run make sync-bootstrap, repin, "
            "and publish the Workshop Studio asset"
        )
    bootstrap_sha = hashlib.sha256(source_bytes).hexdigest()

    contentspec = contentspec_path.read_text(encoding="utf-8")
    main_template = main_template_path.read_text(encoding="utf-8")
    editor_template = editor_template_path.read_text(encoding="utf-8")
    consumers = {
        "contentspec.SourceRevision": _parameter_default(
            contentspec, "SourceRevision", "contentspec.yaml"
        ),
        "main.SourceRevision": _cfn_default(
            main_template, "SourceRevision", "hybrid-retrieval-main.yml"
        ),
        "contentspec.BootstrapScriptSha256": _parameter_default(
            contentspec, "BootstrapScriptSha256", "contentspec.yaml"
        ),
        "main.BootstrapScriptSha256": _cfn_default(
            main_template,
            "BootstrapScriptSha256",
            "hybrid-retrieval-main.yml",
        ),
    }
    for name in ("contentspec.SourceRevision", "main.SourceRevision"):
        if consumers[name] != expected_source_sha:
            raise ReleaseContractError(
                f"{name} is {consumers[name]}, expected {expected_source_sha}; "
                "fix: repin Workshop Studio to the tagged source SHA"
            )
    for name in (
        "contentspec.BootstrapScriptSha256",
        "main.BootstrapScriptSha256",
    ):
        if consumers[name] != bootstrap_sha:
            raise ReleaseContractError(
                f"{name} is {consumers[name]}, expected {bootstrap_sha}; "
                "fix: repin after synchronizing the bootstrap asset"
            )

    if "BootstrapScriptSha256: !Ref BootstrapScriptSha256" not in main_template:
        raise ReleaseContractError(
            "main template does not forward BootstrapScriptSha256 to the Code "
            "Editor stack; fix: restore the nested-stack parameter mapping"
        )

    required_editor_fragments = (
        "export SOURCE_REVISION='${SourceRevision}'",
        "'${BootstrapScriptSha256}'",
        "| sha256sum -c -",
    )
    missing = [
        fragment
        for fragment in required_editor_fragments
        if fragment not in editor_template
    ]
    if missing:
        raise ReleaseContractError(
            f"Code Editor delivery omits {missing}; fix: restore SHA forwarding "
            "and verification before certifying the release"
        )

    actual_workshop_head = workshop_head or _git_head(
        workshop_repo,
        "Workshop Studio repository",
    )
    is_workshop_dirty = (
        workshop_dirty
        if workshop_dirty is not None
        else _git_dirty(workshop_repo, "Workshop Studio repository")
    )
    if is_workshop_dirty:
        raise ReleaseContractError(
            "Workshop Studio checkout has uncommitted files; fix: commit and "
            "publish the repin before certifying its delivered asset"
        )
    return {
        "source_sha": expected_source_sha,
        "workshop_studio_sha": actual_workshop_head,
        "bootstrap_sha256": bootstrap_sha,
        "source_bootstrap": str(source_bootstrap),
        "delivered_bootstrap": str(delivered_bootstrap),
        "pin_consumers": consumers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--workshop-repo", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = verify_delivery(
            args.source_repo.resolve(),
            args.workshop_repo.resolve(),
            args.source_sha,
        )
    except (ReleaseContractError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"FAIL: {error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "release-delivery: source, Studio pin, bootstrap asset, and SHA "
        f"consumers agree at {args.source_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
