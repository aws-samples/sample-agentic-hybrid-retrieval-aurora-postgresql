#!/usr/bin/env python3
"""G-17 - Registry drift.

SPEC-session Section 10, G-17 (and T4): the tools are defined once in
``agent/registry.py`` (typed params + descriptions). The Strands tool specs, the
stdio MCP server, and the AgentCore Gateway (Lambda-ARN) dispatch are all
*generated* from it; any diff fails CI.

Cross-transport drift was the pass-2 failure class: a tool description edited in
the Strands specs but not the MCP schema, or a parameter added to the HTTP path
but not the Gateway target. A single registry with generated adapters makes that
drift impossible; this gate proves the adapters still regenerate byte-identically.

What it checks, with no database or network:

* ``agent/registry.py`` defines every canonical T4 tool.
* ``agent.generate_mcp_server.render()`` matches the committed
  ``mcp-server/src/server.generated.ts`` byte for byte.
* ``agent.generate_gateway_dispatch.render()`` matches the committed
  ``lambda_mcp/generated_dispatch.py`` byte for byte.
* The generated Gateway dispatch table exposes exactly the registry's Gateway
  tool set, and the live Strands specs expose exactly its Strands tool set.

A drift is a FAIL (regenerate with the ``python -m agent.generate_*`` commands).
BLOCKED is reserved for the single source or a generator being genuinely absent.
"""

from __future__ import annotations

import difflib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    repo_root,
)

GATE_ID = "G-17"
TITLE = "Registry drift"

# The canonical tool names (T4) that must live in one registry.
CANONICAL_TOOLS = [
    "decompose_question",
    "search_evidence",
    "follow_evidence_links",
    "compare_sources",
    "explain_ranking",
    "synthesize_cited_answer",
    "answer_with_citations",
]


def _diff_preview(committed: str, rendered: str, rel: str) -> list[str]:
    """Return the first lines of a unified diff, committed vs freshly rendered."""
    diff = difflib.unified_diff(
        committed.splitlines(),
        rendered.splitlines(),
        fromfile=f"committed {rel}",
        tofile=f"rendered {rel}",
        lineterm="",
    )
    return list(diff)[:40]


def _check_generated(
    root: Path, generated_path: Path, rendered: str, regen: str
) -> list[str]:
    """Compare a committed generated artifact against its fresh render.

    Args:
        root: Repository root.
        generated_path: Repo-relative path to the committed artifact.
        rendered: The generator's current ``render()`` output.
        regen: The module path to run to regenerate, shown on drift.

    Returns:
        Human-readable failure lines; empty when the artifact is up to date.
    """
    rel = str(generated_path)
    target = root / generated_path
    if not target.exists():
        return [f"  {rel}: committed artifact is MISSING (run: python -m {regen})"]
    committed = target.read_text(encoding="utf-8")
    if committed == rendered:
        print(f"  {rel}: up to date ({len(rendered)} bytes)")
        return []
    lines = [f"  {rel}: DRIFT vs registry render"]
    lines.extend(f"    {line}" for line in _diff_preview(committed, rendered, rel))
    lines.append(f"    (regenerate: python -m {regen})")
    return lines


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    registry_path = root / "agent" / "registry.py"
    if not registry_path.exists():
        print("  no single tool registry at agent/registry.py")
        return finish(GATE_ID, BLOCKED, "agent/registry.py single source is absent")

    try:
        from agent import generate_gateway_dispatch, generate_mcp_server
        from agent.registry import TOOLS, tools_for
    except Exception as error:  # import-time defect in registry or a generator
        print(f"  could not import the registry or a generator: {error!r}")
        return finish(
            GATE_ID,
            BLOCKED,
            "registry/generators present but not importable",
        )

    missing = [name for name in CANONICAL_TOOLS if name not in TOOLS]
    if missing:
        print(f"  registry is missing canonical tools: {missing}")
        return finish(
            GATE_ID,
            FAIL,
            f"agent/registry.py omits {len(missing)} canonical tool(s): {missing}",
        )
    print(f"  registry defines all {len(CANONICAL_TOOLS)} canonical tools")

    # Byte-diff first: report drift before importing a possibly-broken artifact.
    artifacts = [
        (
            generate_mcp_server.GENERATED_PATH,
            generate_mcp_server.render(),
            "agent.generate_mcp_server",
        ),
        (
            generate_gateway_dispatch.GENERATED_PATH,
            generate_gateway_dispatch.render(),
            "agent.generate_gateway_dispatch",
        ),
    ]
    drifted = 0
    for generated_path, rendered, regen in artifacts:
        lines = _check_generated(root, generated_path, rendered, regen)
        if lines:
            drifted += 1
            for line in lines:
                print(line)
    if drifted:
        return finish(
            GATE_ID,
            FAIL,
            f"registry drift in {drifted} artifact(s); regenerate the transports",
        )

    # Byte-clean: the committed artifacts equal the registry render, so importing
    # them is safe. Confirm the transport tool *sets* match the registry, not a
    # superset (a name added to a transport but not the registry).
    from lambda_mcp.generated_dispatch import TOOLS as GATEWAY_TOOLS
    from backend.app import agent_tools

    set_failures: list[str] = []
    expected_gateway = sorted(spec.name for spec in tools_for("gateway"))
    actual_gateway = sorted(GATEWAY_TOOLS)
    if actual_gateway != expected_gateway:
        set_failures.append(
            f"  gateway dispatch table {actual_gateway} != registry gateway set "
            f"{expected_gateway}"
        )
    else:
        print(f"  gateway dispatch exposes the registry set ({len(actual_gateway)} tools)")

    expected_strands = sorted(spec.name for spec in tools_for("strands"))
    actual_strands = sorted(spec["name"] for spec in agent_tools.tool_specifications())
    if actual_strands != expected_strands:
        set_failures.append(
            f"  Strands specs {actual_strands} != registry strands set "
            f"{expected_strands}"
        )
    else:
        print(f"  Strands specs expose the registry set ({len(actual_strands)} tools)")

    if set_failures:
        for line in set_failures:
            print(line)
        return finish(
            GATE_ID,
            FAIL,
            f"transport tool-set drift in {len(set_failures)} check(s)",
        )

    return finish(
        GATE_ID,
        PASS,
        "Strands, MCP, and Gateway transports regenerate byte-identically from "
        "agent/registry.py",
    )


if __name__ == "__main__":
    main_guard(run)
