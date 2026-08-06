#!/usr/bin/env python3
"""G-23 - Route contract (D16, SPEC-session Section 6.0 / Section 10).

Every deep link in the guide must resolve to its intended surface with state
prefilled (preset, role, run_id). SPEC-session:701 scopes G-23 as "verified
headlessly in CI and again on the dry-run laptop": CI proves the route contract
mechanically; the dry-run laptop is where a human confirms the rendered surface.
This gate is the CI half. It proves three things, headlessly and offline, and is
explicit about what it cannot prove (that a click lands on the right rendered DOM
- that needs a live server + browser, the dependency this repo deliberately
avoids, matching G-13's live-server split).

Three checks:

1. Round-trip stability. For every canonical contract route, parseRoute(url)
   then formatRoute(result) must re-encode to the original url. This executes the
   REAL TypeScript router (frontend/src/route.ts) under
   ``node --experimental-strip-types`` rather than a Python reimplementation, so
   there is no twin to drift (the G-17 "one source of truth" principle).

2. Contract-literal membership. Core retrieval and proof links are always
   required. Persona-prefilled agent links are required only when
   ``WORKBENCH_SECURITY_ENABLED=1`` for the optional security module.

3. Built-bundle presence. The built frontend bundle (frontend/dist) must contain
   the preset and persona enum literals the router depends on, to catch a build
   that tree-shook or renamed a route the source defines (the G-14 bundle-scan
   pattern).

Node or the built bundle absent -> BLOCKED, never FAIL: the subject under test is
not present, reported honestly (the _common.py PASS/FAIL/BLOCKED contract).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    repo_root,
    require,
)

GATE_ID = "G-23"
TITLE = "Route contract (D16)"

ROUTE_MODULE = Path("frontend/src/route.ts")
BUNDLE_DIR = Path("frontend/dist")
SCAN_SUFFIXES = {".js"}

# The canonical core deep links the guide sends participants to.
# Each entry is (hash, expected parsed Route). The router must round-trip every
# hash exactly and parse it to the expected surface with state prefilled.
CORE_CONTRACT_ROUTES: list[tuple[str, dict]] = [
    ("#/overview", {"surface": "overview"}),
    ("#/retrieval?preset=exact", {"surface": "retrieval", "preset": "exact"}),
    ("#/retrieval?preset=fuzzy", {"surface": "retrieval", "preset": "fuzzy"}),
    (
        "#/retrieval?preset=semantic",
        {"surface": "retrieval", "preset": "semantic"},
    ),
    ("#/agent", {"surface": "agent"}),
    ("#/proof/rr_9b41d7", {"surface": "proof", "runId": "rr_9b41d7"}),
    (
        "#/proof/rr_9b41d7?lens=timeline",
        {"surface": "proof", "runId": "rr_9b41d7", "lens": "timeline"},
    ),
    (
        "#/proof/rr_9b41d7?lens=supervision",
        {"surface": "proof", "runId": "rr_9b41d7", "lens": "supervision"},
    ),
]

SECURITY_CONTRACT_ROUTES: list[tuple[str, dict]] = [
    (
        "#/agent?role=app_engineer",
        {"surface": "agent", "role": "app_engineer"},
    ),
    (
        "#/agent?role=dba",
        {"surface": "agent", "role": "dba"},
    ),
    (
        "#/agent?role=auditor",
        {"surface": "agent", "role": "auditor"},
    ),
]

CORE_BUNDLE_LITERALS = ["exact", "fuzzy", "semantic"]
SECURITY_BUNDLE_LITERALS = ["app_engineer", "dba", "auditor"]


def _security_enabled() -> bool:
    value = os.environ.get("WORKBENCH_SECURITY_ENABLED", "")
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _contract_routes() -> list[tuple[str, dict]]:
    routes = list(CORE_CONTRACT_ROUTES)
    if _security_enabled():
        routes.extend(SECURITY_CONTRACT_ROUTES)
    return routes


def _bundle_literals() -> list[str]:
    literals = list(CORE_BUNDLE_LITERALS)
    if _security_enabled():
        literals.extend(SECURITY_BUNDLE_LITERALS)
    return literals

# Node harness: import the real router, run parse+format for each contract route,
# and emit one JSON line per route so the Python side can diff against the
# expected parse without maintaining a second router implementation.
_HARNESS = """
import {{ parseRoute, formatRoute }} from {module!r};
const routes = {routes};
const out = [];
for (const [hash, expected] of routes) {{
  const parsed = parseRoute(hash);
  const reencoded = formatRoute(parsed);
  out.push({{ hash, expected, parsed, reencoded }});
}}
process.stdout.write(JSON.stringify(out));
"""


def _iter_bundle_js(bundle: Path):
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def _run_router_harness(node: str, module_path: Path) -> list[dict]:
    routes = _contract_routes()
    harness = _HARNESS.format(
        module=str(module_path),
        routes=json.dumps([[h, e] for h, e in routes]),
    )
    harness_path = module_path.parent / ".g23_route_harness.mjs"
    harness_path.write_text(harness, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, "--experimental-strip-types", str(harness_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError(
            f"router harness failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:400]}"
        )
    return json.loads(result.stdout)


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    bundle_literals = _bundle_literals()

    module_path = root / ROUTE_MODULE
    if not module_path.is_file():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{ROUTE_MODULE} absent; PR-5 router not built yet",
        )

    node = shutil.which("node")
    if not node:
        return finish(
            GATE_ID,
            BLOCKED,
            "node not on PATH; cannot execute the router for round-trip check",
        )

    try:
        harness_out = _run_router_harness(node, module_path)
    except AssertionError as exc:
        # Node too old for --experimental-strip-types is an environment gap, not
        # a router defect: report BLOCKED so CI without Node 22+ stays honest.
        if "strip-types" in str(exc) or "Unknown" in str(exc):
            return finish(GATE_ID, BLOCKED, f"node cannot strip TS types: {exc}")
        raise

    # Checks 1 + 2: round-trip stability and contract-literal membership.
    for row in harness_out:
        require(
            row["reencoded"] == row["hash"],
            f"round-trip broke: {row['hash']} -> {row['parsed']} -> "
            f"{row['reencoded']}",
        )
        require(
            row["parsed"] == row["expected"],
            f"{row['hash']} parsed to {row['parsed']}, expected "
            f"{row['expected']}",
        )
    print(f"  round-trip + contract parse: {len(harness_out)} routes OK")

    # Check 3: the built bundle still contains the router's enum literals.
    bundle = root / BUNDLE_DIR
    if not bundle.is_dir():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{BUNDLE_DIR} not built; run the frontend build to scan the bundle",
        )
    js_files = list(_iter_bundle_js(bundle))
    if not js_files:
        return finish(GATE_ID, BLOCKED, f"{BUNDLE_DIR} has no .js assets")
    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in js_files
    )
    missing = [lit for lit in bundle_literals if lit not in corpus]
    require(
        not missing,
        f"built bundle missing route literal(s): {missing} - a build tree-shook "
        "or renamed a route the source defines",
    )
    print(f"  bundle literals present: {', '.join(bundle_literals)}")

    return finish(
        GATE_ID,
        PASS,
        f"{len(harness_out)} contract routes round-trip; bundle literals present",
    )


if __name__ == "__main__":
    main_guard(run)
