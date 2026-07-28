#!/usr/bin/env python3
"""Promote a captured pg incident into an `admission payload v1` document.

Thin adapter (D21/D19): reads capture artifacts and emits a payload on stdout.
Produces payloads only — it never connects to a database. When no live capture
is present it emits the checked-in fixture and says so on stderr; it never
fabricates incident data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"


def build_payload(capture_dir: Path, fixture: Path) -> dict:
    capture = capture_dir / "lock_capture.json"
    if capture.is_file():
        raw = json.loads(capture.read_text(encoding="utf-8"))
        return _payload_from_capture(raw)
    print(f"promote_pg_incident: no capture at {capture}; using fixture {fixture}", file=sys.stderr)
    return json.loads(fixture.read_text(encoding="utf-8"))


def _payload_from_capture(raw: dict) -> dict:
    """Map a raw lock-capture record to admission payload v1."""
    s = raw["structured"] if "structured" in raw else raw
    return {
        "schema": "admission payload v1",
        "source": {"system": "pg_incident_capture", "uri": raw["source_uri"],
                   "observation_window": raw.get("observation_window", {})},
        "kind": "lock_evidence",
        "external_key": raw["external_key"],
        "title": raw["title"],
        "occurred_at": raw["occurred_at"],
        "available_at": raw.get("available_at"),
        "acl": raw.get("acl", {"visibility": "workshop"}),
        "body": raw["body"],
        "structured": s,
        "links": raw.get("links", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit an admission payload v1 on stdout.")
    ap.add_argument("--capture-dir", type=Path, default=Path("/run/verity"))
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = ap.parse_args()
    payload = build_payload(args.capture_dir, args.fixture)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
