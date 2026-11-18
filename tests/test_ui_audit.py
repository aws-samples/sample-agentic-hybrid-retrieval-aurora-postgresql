"""The UI audit fails on everything but the named exemption, at its recorded range.

Each case is a falsifier kept as a test: the check passes only on the report it was
granted for, and every way that report can change fails with a message naming the fix.
"""

from __future__ import annotations

import io
import json

import pytest

from scripts.checks import ui_audit

PICOMATCH = {
    "source": 1247710,
    "name": "picomatch",
    "dependency": "picomatch",
    "title": "picomatch vulnerable to ReDoS through single-branch repeated extglobs",
    "url": "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
    "severity": "high",
    "range": "<=4.0.7",
}


def report(*advisories: dict) -> dict:
    """An `npm audit --json` report shaped like the one of 18 November 2026."""
    vulnerabilities = {
        "vite": {"severity": "high", "via": ["picomatch", "tinyglobby"]},
        "tinyglobby": {"severity": "high", "via": ["fdir", "picomatch"]},
    }
    for advisory in advisories:
        vulnerabilities[advisory["name"]] = {
            "severity": advisory["severity"],
            "via": [advisory],
        }
    return {"auditReportVersion": 2, "vulnerabilities": vulnerabilities, "metadata": {}}


def run(payload: str, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    code = ui_audit.main()
    return code, capsys.readouterr().out


def test_the_exempted_advisory_alone_passes_and_names_its_exit(monkeypatch, capsys):
    code, out = run(json.dumps(report(PICOMATCH)), monkeypatch, capsys)
    assert code == 0
    assert out.startswith("ui-audit: PASS")
    assert "GHSA-fc5q-39xc-vjpf" in out and "Exit:" in out


def test_another_moderate_advisory_fails_by_its_id(monkeypatch, capsys):
    other = {
        **PICOMATCH,
        "name": "esbuild",
        "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
        "severity": "moderate",
        "range": "<0.25.0",
    }
    code, out = run(json.dumps(report(PICOMATCH, other)), monkeypatch, capsys)
    assert code == 1
    assert "GHSA-aaaa-bbbb-cccc (esbuild <0.25.0, moderate) has no exemption" in out


def test_a_low_advisory_stays_below_the_threshold(monkeypatch, capsys):
    low = {
        **PICOMATCH,
        "name": "minimist",
        "url": "https://github.com/advisories/GHSA-low0-low0-low0",
        "severity": "low",
    }
    code, _ = run(json.dumps(report(PICOMATCH, low)), monkeypatch, capsys)
    assert code == 0


def test_a_changed_range_means_a_fix_shipped_and_fails(monkeypatch, capsys):
    fixed = {**PICOMATCH, "range": "<4.0.8"}
    code, out = run(json.dumps(report(fixed)), monkeypatch, capsys)
    assert code == 1
    assert "now reports picomatch <4.0.8" in out and "delete the exemption" in out


def test_an_exemption_no_longer_reported_is_stale_and_fails(monkeypatch, capsys):
    code, out = run(json.dumps(report()), monkeypatch, capsys)
    assert code == 1
    assert "GHSA-fc5q-39xc-vjpf is exempted but no longer reported" in out


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"error": {"code": "ENOAUDIT", "summary": "registry unreachable"}}),
        json.dumps({"error": "audit endpoint returned 503"}),
        "npm ERR! network request failed",
        "",
    ],
)
def test_no_report_fails_instead_of_passing_silently(payload, monkeypatch, capsys):
    code, out = run(payload, monkeypatch, capsys)
    assert code == 1
    assert out.startswith("ui-audit: FAIL")
