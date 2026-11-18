#!/usr/bin/env python3
"""Fail the build on any UI dependency advisory except the named exemptions below.

`npm audit --audit-level=moderate` has no way to set one advisory aside, so this check
reads `npm audit --json` and applies the same threshold itself. An exemption is granted
for one advisory, on one package, at the exact vulnerable range it was granted for. The
check fails when another advisory reaches the threshold, when an exempted advisory's
range changes (upstream has probably published a fix), when an exempted advisory is no
longer reported (the exemption is stale), or when npm returns an error instead of a
report.

Usage
-----
    { npm --prefix ui audit --json || true; } | python3 scripts/checks/ui_audit.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

SEVERITY_ORDER = ("info", "low", "moderate", "high", "critical")
THRESHOLD = "moderate"


@dataclass(frozen=True)
class Exemption:
    """One advisory set aside, with why and when the exemption ends."""

    package: str
    vulnerable_range: str
    reason: str
    exit_condition: str


EXEMPTIONS = {
    # Granted 18 November 2026 (owner, versions rule 9). GHSA-fc5q-39xc-vjpf was widened on
    # 17 November to every picomatch release, and 4.0.7 is the latest, so no fix exists.
    "GHSA-fc5q-39xc-vjpf": Exemption(
        package="picomatch",
        vulnerable_range="<=4.0.7",
        reason=(
            "ReDoS in glob patterns; picomatch reaches the UI only through the build "
            "tools vite and vitest with patterns the repository writes, never in the "
            "shipped bundle, and npm's only fix is a major downgrade to vite 6.2.7"
        ),
        exit_condition=(
            "picomatch publishes a fixed release: the advisory's range changes, this "
            "check fails, and the lockfile moves to the fix and the exemption is deleted"
        ),
    ),
}


def advisory_id(advisory: dict) -> str:
    """The GHSA identifier at the end of an advisory's URL."""
    return str(advisory.get("url", "")).rstrip("/").rsplit("/", 1)[-1]


def reported_advisories(report: dict) -> list[dict]:
    """Every advisory npm attaches to a vulnerable package, at or above the threshold."""
    floor = SEVERITY_ORDER.index(THRESHOLD)
    found = []
    for name, vulnerability in report["vulnerabilities"].items():
        for via in vulnerability.get("via", []):
            if not isinstance(via, dict):
                continue
            if SEVERITY_ORDER.index(via.get("severity", "critical")) >= floor:
                found.append({**via, "package": via.get("name", name)})
    return found


def problems(report: dict) -> list[str]:
    """What fails the audit, each naming the rule, the value and the nearest fix."""
    if "error" in report or "vulnerabilities" not in report:
        error = report.get("error")
        detail = error.get("summary") if isinstance(error, dict) else error
        return [
            "npm audit returned no report"
            + (f" ({detail})" if detail else "")
            + "; rerun `npm --prefix ui audit --json` and fix the npm error first"
        ]
    found = []
    seen = set()
    for advisory in reported_advisories(report):
        ghsa = advisory_id(advisory)
        exemption = EXEMPTIONS.get(ghsa)
        if exemption is None:
            found.append(
                f"{ghsa} ({advisory['package']} {advisory.get('range')}, "
                f"{advisory.get('severity')}) has no exemption; update the package, "
                "or grant a named exemption with its reason and exit condition"
            )
            continue
        seen.add(ghsa)
        if (advisory["package"], advisory.get("range")) != (
            exemption.package,
            exemption.vulnerable_range,
        ):
            found.append(
                f"{ghsa} now reports {advisory['package']} {advisory.get('range')}, not "
                f"the {exemption.package} {exemption.vulnerable_range} it was exempted "
                "for; a fix has probably shipped, so update the lockfile and delete the "
                "exemption"
            )
    for ghsa in sorted(EXEMPTIONS.keys() - seen):
        found.append(
            f"{ghsa} is exempted but no longer reported; delete its exemption from "
            "scripts/checks/ui_audit.py"
        )
    return found


def main() -> int:
    """Read `npm audit --json` from stdin and print the verdict."""
    raw = sys.stdin.read()
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        print(
            "ui-audit: FAIL\n  npm audit printed no JSON; rerun it and read its error"
        )
        return 1
    found = problems(report)
    if found:
        print("ui-audit: FAIL")
        for line in found:
            print(f"  {line}")
        return 1
    print("ui-audit: PASS")
    for ghsa, exemption in EXEMPTIONS.items():
        print(
            f"  exempt: {ghsa} ({exemption.package} {exemption.vulnerable_range}). "
            f"Exit: {exemption.exit_condition}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
