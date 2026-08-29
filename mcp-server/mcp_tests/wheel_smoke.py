"""Build and exercise the MCP wheel without the repository on ``sys.path``."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MCP_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], **kwargs: Any) -> None:
    subprocess.run(command, check=True, **kwargs)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _discovery_request(port: int) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "wheel-smoke",
                        "version": "1.0",
                    },
                }
            },
        }
    ).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "server/discover",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1) as response:
        return json.load(response)


def _exercise_installed_wheel() -> None:
    if importlib.util.find_spec("service") is not None:
        raise SystemExit(
            "wheel smoke found repository package 'service'; fix: run the "
            "installed phase outside the source tree with PYTHONPATH unset"
        )

    from catalog_mcp import server

    if server.mcp.name != "mosaic-retrieval":
        raise SystemExit(
            f"wheel loaded MCP name {server.mcp.name!r}; "
            "fix: package the canonical catalog_mcp server"
        )

    executable = Path(sys.executable).parent / "mosaic-retrieval-mcp"
    if not executable.is_file():
        raise SystemExit(
            f"wheel did not install {executable}; "
            "fix: restore the project.scripts entry point"
        )

    port = _free_port()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": str(port),
            "PYTHONNOUSERSITE": "1",
        }
    )
    process = subprocess.Popen(
        [str(executable)],
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise SystemExit(
                    f"installed MCP exited with {process.returncode}; output:\n{output}"
                )
            try:
                response = _discovery_request(port)
                break
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(0.1)
        else:
            raise SystemExit(
                f"installed MCP did not answer discovery within 15 seconds: "
                f"{last_error}"
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    versions = response.get("result", {}).get("supportedVersions")
    if versions != ["2026-07-28"]:
        raise SystemExit(
            f"wheel discovery returned supportedVersions={versions!r}; "
            "fix: serve the pinned MCP 2026-07-28 protocol"
        )
    print("wheel-smoke: isolated install and MCP discovery passed")


def _build_and_exercise(uv: str) -> None:
    _run([uv, "lock", "--project", str(MCP_ROOT), "--check"])
    with tempfile.TemporaryDirectory(prefix="mosaic-mcp-wheel-") as directory:
        temporary = Path(directory)
        project = temporary / "project"
        distribution = temporary / "dist"
        virtualenv = temporary / "venv"
        requirements = temporary / "requirements.txt"
        shutil.copytree(
            MCP_ROOT,
            project,
            ignore=shutil.ignore_patterns(
                ".pytest_cache",
                ".venv",
                "__pycache__",
                "build",
                "dist",
                "*.egg-info",
            ),
        )

        _run(
            [
                uv,
                "build",
                "--project",
                str(project),
                "--wheel",
                "--out-dir",
                str(distribution),
                "--no-build-logs",
            ]
        )
        wheels = list(distribution.glob("mosaic_retrieval_mcp-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(
                f"wheel build produced {len(wheels)} matching files; "
                "fix: clear duplicate distributions and build exactly one wheel"
            )

        _run([uv, "venv", "--python", "3.13", str(virtualenv)])
        _run(
            [
                uv,
                "export",
                "--project",
                str(project),
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                str(requirements),
                "--quiet",
            ]
        )
        python = virtualenv / "bin" / "python"
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "-r",
                str(requirements),
                "--quiet",
            ]
        )
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(wheels[0]),
                "--quiet",
            ]
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        _run(
            [str(python), str(Path(__file__).resolve()), "--installed"],
            cwd=temporary,
            env=environment,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    if args.installed:
        _exercise_installed_wheel()
    else:
        _build_and_exercise(args.uv)


if __name__ == "__main__":
    main()
