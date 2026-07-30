#!/usr/bin/env python3
"""G-13 - Verify-SQL golden test.

SPEC-session Section 10, G-13: for the smoke ``run_id``, execute every
``_verify_sql`` the API publishes and diff the replayed rows against the API JSON
- zero mismatches.

Law 2 (psql parity): nothing renders in the Hybrid Retrieval Workbench that cannot be
reproduced from psql with a ``run_id``. Every data panel returns a ``_verify_sql``
descriptor - the exact statement the endpoint executed, from the one canonical
registry (``backend/app/verify_sql.py``), not a hand-maintained twin. This gate is
the drift check: a mismatch means the workbench shows a number psql cannot
reproduce, which is the defect G-13 exists to catch.

Grain of reproducibility (Section 6.2):

* **Panel grain** - the receipt family (run / candidates / stages / answer) is one
  ``run_id``-bound SELECT per panel. The gate replays each and diffs the panel.
* **Element grain** - composite panels (graph edges, timeline events) publish one
  single-key SELECT per element. The gate replays each element's statement and
  diffs it against that element's row.
* **Not run-bound** - the live EXPLAIN plan and the evaluation leaderboard carry
  an honest ``{"reproducible": false, "reason": ...}`` marker instead of a query;
  the gate records them as intentionally unverifiable, never as a pass it skipped.

How the smoke run_id is obtained (never by discovery):

* ``WORKBENCH_SMOKE_RUN_ID`` if set, else the ``smoke run_id`` line in the readiness
  report (``WORKBENCH_READINESS_FILE`` or ``READINESS.md`` at the repo root), which
  bootstrap stage S8 writes from its live ``POST /v1/agent/answer``. If neither is
  present the gate is BLOCKED with the remedy - it never falls back to "most recent
  run", which is nondeterministic and could select a participant's in-flight run.

The API JSON is read over HTTP (the bytes the browser receives), so serialization
is exercised on the wire; the receipt/graph/timeline panels are GET-only, so the
gate stays read-only against live Aurora and is repeatable before doors open.
Replay runs in a ``READ ONLY`` transaction with a bounded ``statement_timeout``;
this gate issues only SELECT and never mutates anything.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    repo_root,
    require,
)

GATE_ID = "G-13"
TITLE = "Verify-SQL golden test"

DEFAULT_API_BASE = "http://127.0.0.1:8000"
HTTP_TIMEOUT_SECONDS = 20
REPLAY_STATEMENT_TIMEOUT_MS = 15000
_SMOKE_RUN_ID_PATTERN = re.compile(
    r"smoke\s+run[_ ]id[^0-9a-f]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def _smoke_run_id() -> tuple[str | None, str]:
    """Resolve the smoke run_id from the environment or the readiness report.

    Returns:
        ``(run_id, source)`` where ``run_id`` is None when neither source exists.
        ``source`` names where it came from (or where the gate looked).
    """
    from_env = read_env_value("WORKBENCH_SMOKE_RUN_ID")
    if from_env:
        return from_env.strip(), "WORKBENCH_SMOKE_RUN_ID"

    configured = read_env_value("WORKBENCH_READINESS_FILE")
    readiness = Path(configured) if configured else repo_root() / "READINESS.md"
    if not readiness.exists():
        return None, f"no readiness report at {readiness}"
    match = _SMOKE_RUN_ID_PATTERN.search(readiness.read_text(encoding="utf-8"))
    if not match:
        return None, f"no 'smoke run_id' line in {readiness}"
    return match.group(1), str(readiness)


def _get_json(api_base: str, path: str) -> dict[str, Any]:
    """GET ``path`` from the running API and return the decoded JSON body."""
    url = f"{api_base.rstrip('/')}{path}"
    request = urllib_request.Request(url, headers={"Accept": "application/json"})
    with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _encode(value: Any) -> Any:
    """Encode a replayed DB row the way FastAPI encodes the wire JSON.

    Replay reads Decimal/datetime/UUID from Aurora; the API serialized the same
    columns through FastAPI's JSON encoder. Comparing both sides after the same
    encoding is what makes "same bytes" a meaningful, false-positive-free diff.
    """
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


def _replay(cur, descriptor: dict[str, Any], label: str) -> Any:
    """Execute one ``_verify_sql`` descriptor under its own identity.

    The descriptor's ``set_role`` is issued before its ``statement`` so the replay
    runs as the persona the panel ran as. Under RLS the same SELECT returns
    different rows per role, so replaying without the role would diff the API's
    rows against a *different* query's rows and call the mismatch a defect.

    SET LOCAL, not SET: the caller's transaction is rolled back at the end
    (:246), so the role never outlives this descriptor.

    The two envelope assertions live here rather than in the callers because this
    is the one choke point both grains share. Asserting them per-caller left the
    element grain (graph edges, timeline events) unchecked, so a regression that
    dropped ``set_role`` on that path alone would have replayed as the pool login
    and still passed.
    """
    require(
        descriptor["statement"].count(";") == 0,
        f"{label} _verify_sql.statement contains a ';' — it must be one "
        "parameterized SELECT; the multi-statement envelope belongs in "
        "'rendered', which humans paste and machines never execute",
    )
    require(
        descriptor.get("set_role", "").startswith("SET LOCAL ROLE persona_"),
        f"{label} _verify_sql is missing its A3 identity envelope",
    )
    set_role = descriptor.get("set_role")
    if set_role:
        # A savepoint per descriptor: SET LOCAL ROLE persists to the end of the
        # transaction, and the next descriptor may need a different persona.
        cur.execute("SAVEPOINT verify_role")
        cur.execute(set_role)
    try:
        cur.execute(descriptor["statement"], descriptor["binds"])
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        if set_role:
            cur.execute("ROLLBACK TO SAVEPOINT verify_role")
    return _encode(rows)


class Mismatch(Exception):
    """Raised when replayed rows do not equal the API JSON for a panel."""


def _require_equal(label: str, replayed: Any, published: Any) -> str:
    """Return an OK line, or raise :class:`Mismatch` with a compact diff."""
    if replayed == published:
        count = len(replayed) if isinstance(replayed, list) else 1
        return f"  {label}: replay == API ({count} row(s))"
    published_text = json.dumps(published, sort_keys=True, default=str)
    replayed_text = json.dumps(replayed, sort_keys=True, default=str)
    raise Mismatch(
        f"{label}: replay != API\n"
        f"    API json:  {published_text[:400]}\n"
        f"    replayed:  {replayed_text[:400]}"
    )


def _check_receipt(cur, api_base: str, run_id: str, ok_lines: list[str]) -> None:
    """Diff the four panel-grain receipt panels for the smoke run."""
    receipt = _get_json(api_base, f"/v1/runs/{run_id}")
    verify = receipt.get("_verify_sql")
    if not verify:
        raise Mismatch(
            f"/v1/runs/{run_id} carries no _verify_sql (registry not attached)"
        )
    single_row = {"run", "answer"}
    for panel, descriptor in verify.items():
        published = receipt[panel]
        replayed = _replay(cur, descriptor, f"receipt.{panel}")
        if panel in single_row:
            replayed = replayed[0] if replayed else None
        ok_lines.append(_require_equal(f"receipt.{panel}", replayed, published))


def _check_elements(
    cur,
    api_base: str,
    run_id: str,
    path: str,
    collection: str,
    label: str,
    ok_lines: list[str],
) -> None:
    """Diff each element-grain drawer (graph edges / timeline events)."""
    panel = _get_json(api_base, path)
    elements = panel.get(collection) or []
    verified = 0
    for element in elements:
        descriptor = element.get("_verify_sql")
        if not descriptor:
            raise Mismatch(f"{label} element carries no _verify_sql: {element!r}")
        replayed = _replay(cur, descriptor, f"{label}[{verified}]")
        row = replayed[0] if replayed else None
        published = {k: v for k, v in element.items() if k != "_verify_sql"}
        _require_equal(f"{label}[{verified}]", row, published)
        verified += 1
    ok_lines.append(f"  {label}: {verified} element(s) replay == API")


def run() -> int:
    print_header(GATE_ID, TITLE)

    run_id, source = _smoke_run_id()
    if not run_id:
        print(f"  {source}")
        print("  remedy: run `make smoke` (bootstrap stage S8 / backend/scripts/")
        print("  smoke_test.py), which answers the canonical question and records the")
        print("  smoke run_id in READINESS.md, or set WORKBENCH_SMOKE_RUN_ID directly.")
        return finish(GATE_ID, BLOCKED, "no smoke run_id (readiness report / env)")
    print(f"  smoke run_id: {run_id} (from {source})")

    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")
    try:
        import psycopg  # noqa: F401
        from psycopg.rows import dict_row
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable in this interpreter")
    try:
        import fastapi.encoders  # noqa: F401
    except ImportError:
        return finish(GATE_ID, BLOCKED, "fastapi is not importable in this interpreter")

    api_base = read_env_value("RETRIEVAL_API_URL") or DEFAULT_API_BASE
    print(f"  api: {api_base}")
    print(f"  engine: {redact_dsn(dsn)}")

    import psycopg

    ok_lines: list[str] = []
    try:
        with psycopg.connect(
            dsn, connect_timeout=15, autocommit=False, row_factory=dict_row
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(REPLAY_STATEMENT_TIMEOUT_MS),),
                )
                _check_receipt(cur, api_base, run_id, ok_lines)
                _check_elements(
                    cur,
                    api_base,
                    run_id,
                    f"/v1/runs/{run_id}/graph",
                    "edges",
                    "graph.edge",
                    ok_lines,
                )
                _check_elements(
                    cur,
                    api_base,
                    run_id,
                    f"/v1/runs/{run_id}/timeline",
                    "events",
                    "timeline.event",
                    ok_lines,
                )
            conn.rollback()
    except Mismatch as mismatch:
        for line in ok_lines:
            print(line)
        print(f"  {mismatch}")
        return finish(GATE_ID, FAIL, "a panel's _verify_sql does not reproduce its API JSON")
    except urllib_error.URLError as error:
        return finish(
            GATE_ID,
            BLOCKED,
            f"workbench API not reachable at {api_base} ({error.reason}); "
            "start it (systemctl restart workbench) and retry",
        )

    for line in ok_lines:
        print(line)
    return finish(
        GATE_ID,
        PASS,
        f"every published _verify_sql reproduces its API JSON for run {run_id}",
    )


if __name__ == "__main__":
    main_guard(run)
